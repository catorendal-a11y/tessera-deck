"""A tool's permission prompt answered on the panel: only a touch allows, and everything unclear falls back."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import cockpit
import deckctl
import permission
from control_api import ControlServer
from host_support import HostCase


def hook_event(**tool_input):
    return {'hook_event_name': 'PermissionRequest', 'tool_name': 'Bash', 'tool_input': tool_input}


class RequestTextTests(unittest.TestCase):
    def test_a_command_is_shown_as_it_will_run_and_the_description_is_left_out(self):
        self.assertEqual(permission.request_text(hook_event(command='npm test', description='Run the tests')), 'Bash: npm test')

    def test_every_other_argument_is_shown_so_nothing_is_approved_unseen(self):
        text = permission.request_text(hook_event(command='npm test', run_in_background=True))
        self.assertIn('"run_in_background":true', text)
        self.assertIn('"command":"npm test"', text)

    def test_what_cannot_be_shown_in_full_is_refused(self):
        for payload in (hook_event(command='x' * 200), hook_event(command='rm -rf ‮ ~'), hook_event(command='a\nb'),
                        {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': 'ls'}},
                        {'hook_event_name': 'PermissionRequest', 'tool_name': 'Ba sh', 'tool_input': {'command': 'ls'}},
                        'not an object', None):
            with self.assertRaises(ValueError, msg=repr(payload)[:60]):
                permission.request_text(payload)

    def test_only_allow_and_deny_become_hook_output(self):
        self.assertEqual(permission.hook_output('deny')['hookSpecificOutput']['decision'], {'behavior': 'deny'})
        for nothing in (None, 'ask', 'ALLOW', ''):
            with self.assertRaises(ValueError):
                permission.hook_output(nothing)


class DeskTests(unittest.TestCase):
    def ask_in_thread(self, desk, timeout=5.0):
        result = []
        thread = threading.Thread(target=lambda: result.append(desk.ask('claude', 'Bash: ls', lambda: True, timeout)))
        thread.start()
        for _ in range(200):
            if desk.current():
                break
            time.sleep(0.005)
        return thread, result

    def test_the_touch_is_the_answer(self):
        desk = permission.Desk()
        thread, result = self.ask_in_thread(desk)
        self.assertEqual(desk.current(), {'agent': 'claude', 'text': 'Bash: ls'})
        self.assertTrue(desk.answer('claude', 'allow'))
        thread.join(5)
        self.assertEqual(result, ['allow'])
        self.assertIsNone(desk.current())

    def test_nobody_answering_is_no_answer(self):
        desk = permission.Desk()
        self.assertIsNone(desk.ask('claude', 'Bash: ls', lambda: True, timeout=0.05))
        self.assertIsNone(desk.current())
        self.assertFalse(desk.answer('claude', 'allow'), 'a late touch must not answer a later question')

    def test_no_panel_a_second_question_or_a_wrong_button_gives_no_answer(self):
        desk = permission.Desk()
        self.assertIsNone(desk.ask('claude', 'Bash: ls', lambda: False))
        thread, result = self.ask_in_thread(desk)
        self.assertIsNone(desk.ask('claude', 'Bash: rm', lambda: True, timeout=0.05), 'one question at a time')
        self.assertFalse(desk.answer('codex', 'allow'))
        self.assertFalse(desk.answer('claude', 'open'))
        self.assertTrue(desk.answer('claude', 'deny'))
        thread.join(5)
        self.assertEqual(result, ['deny'])


class PanelQuestionTests(HostCase):
    def cockpit_daemon(self):
        daemon = self.daemon()
        daemon.device_info = {'protocol': 4}
        return daemon

    def test_an_open_question_is_the_agents_lane_and_brings_its_screen_forward(self):
        daemon = self.cockpit_daemon()
        with patch.object(daemon.permissions, 'current', return_value={'agent': 'claude', 'text': 'Bash: npm test'}):
            daemon.handle_job(('question',))
        sent = [call.args[0] for call in daemon.panel.send_line.call_args_list]
        self.assertIn('AD_VIEW agents', sent)
        lanes = json.loads(next(line for line in sent if line.startswith('AD_AGENTS ')).split(' ', 1)[1])['agents']
        self.assertEqual((lanes[0]['id'], lanes[0]['state'], lanes[0]['text']), ('claude', 'waiting', 'Bash: npm test'))

    def test_allow_on_the_panel_answers_the_question_instead_of_opening_the_window(self):
        daemon = self.cockpit_daemon()
        import daemon_ticks
        result = []
        thread = threading.Thread(target=lambda: result.append(daemon.ask_permission('claude', 'Bash: npm test')))
        thread.start()
        for _ in range(200):
            if daemon.permissions.current():
                break
            time.sleep(0.005)
        with patch.object(daemon_ticks, 'focus_existing_process') as focus:
            daemon.handle_job(('agent', 'claude', 'allow'))
        thread.join(5)
        self.assertEqual(result, ['allow'])
        focus.assert_not_called()

    def test_an_older_panel_is_never_asked(self):
        daemon = self.daemon()
        daemon.device_info = {'protocol': 3}
        self.assertIsNone(daemon.ask_permission('claude', 'Bash: npm test'))

    def test_the_lane_text_of_a_question_is_not_shortened(self):
        text = 'Bash: ' + 'x' * (permission.MAX_TEXT - 6)
        lanes = json.loads(cockpit.agents_payload({}, {}, {'agent': 'claude', 'text': text}))['agents']
        self.assertEqual(lanes[0]['text'], text)


class HookTests(HostCase):
    def serve(self, decision):
        daemon = self.daemon()
        daemon.ask_permission = lambda agent, text: decision
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        api = ControlServer(daemon, Path(directory.name) / 'deck-api.local.json')
        api.start()
        self.addCleanup(api.stop)
        return api

    def run_hook(self, api, event):
        out = io.StringIO()
        self.assertEqual(deckctl.permission_hook(io.StringIO(json.dumps(event)), api.info_path, out), 0)
        return out.getvalue()

    def test_the_panels_answer_is_printed_the_way_claude_code_expects(self):
        printed = self.run_hook(self.serve('allow'), hook_event(command='npm test'))
        self.assertEqual(json.loads(printed), {'hookSpecificOutput': {'hookEventName': 'PermissionRequest',
                                                                      'decision': {'behavior': 'allow'}}})

    def test_no_answer_an_unshowable_request_or_a_stopped_host_prints_nothing(self):
        self.assertEqual(self.run_hook(self.serve(None), hook_event(command='npm test')), '')
        self.assertEqual(self.run_hook(self.serve('allow'), hook_event(command='x' * 500)), '')
        out = io.StringIO()
        self.assertEqual(deckctl.permission_hook(io.StringIO(json.dumps(hook_event(command='ls'))), Path('missing.json'), out), 0)
        self.assertEqual(out.getvalue(), '')
        self.assertEqual(deckctl.permission_hook(io.StringIO('{broken'), Path('missing.json'), out), 0)

    def test_a_plugin_token_may_not_ask(self):
        api = self.serve('allow')
        token = api.add_grant('demo', ('var', 'vars', 'press'))
        with self.assertRaises(deckctl.DeckctlError):
            deckctl.call({'port': api.server.server_port, 'token': token}, 'POST', '/v1/permission',
                         {'agent': 'claude', 'text': 'Bash: ls'})

    def test_the_settings_block_runs_the_hook_with_a_timeout_longer_than_the_wait(self):
        block = deckctl.hooks_block('claude-permission')['hooks']['PermissionRequest'][0]['hooks'][0]
        self.assertTrue(block['command'].endswith('permission'))
        self.assertGreater(block['timeout'], permission.WAIT_SECONDS)


if __name__ == '__main__':
    unittest.main()
