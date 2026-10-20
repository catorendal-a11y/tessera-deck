"""AI tool adapters, the batch variables route and the deckctl adapter/hooks commands."""
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import adapters
import deckctl
from action_runner import Busy
from control_api import ControlServer


class ClaudeTests(unittest.TestCase):
    def event(self, name, **fields):
        return adapters.claude(dict({'hook_event_name': name, 'cwd': r'C:\Users\Jane\code\my-project'}, **fields))

    def test_working_waiting_idle_and_ended(self):
        self.assertEqual(self.event('UserPromptSubmit')['claude'], 'working')
        self.assertEqual(self.event('PostToolUse')['claude'], 'working')
        tool = self.event('PreToolUse', tool_name='Bash')
        self.assertEqual((tool['claude'], tool['claude.tool']), ('working', 'Bash'))
        waiting = self.event('Notification', message='Claude needs your permission to use Bash')
        self.assertEqual((waiting['claude'], waiting['claude.message']),
                         ('waiting', 'Claude needs your permission to use Bash'))
        for finished in ('Stop', 'SubagentStop', 'SessionStart'):
            done = self.event(finished)
            self.assertEqual((done['claude'], done['claude.tool'], done['claude.message']), ('idle', '', ''))
        self.assertEqual(self.event('SessionEnd')['claude'], 'ended')

    def test_the_project_is_the_folder_name_for_windows_and_posix_paths(self):
        self.assertEqual(self.event('Stop')['claude.project'], 'my-project')
        posix = adapters.claude({'hook_event_name': 'Stop', 'cwd': '/home/jane/work/api'})
        self.assertEqual(posix['claude.project'], 'api')
        self.assertNotIn('claude.project', adapters.claude({'hook_event_name': 'Stop'}))

    def test_unknown_or_malformed_events_change_nothing(self):
        for event in ({}, {'hook_event_name': 'PreCompact'}, {'hook_event_name': 5}, {'hook_event_name': None}):
            self.assertEqual(adapters.claude(event), {}, msg=repr(event))

    def test_long_text_is_cut_and_whitespace_collapsed(self):
        message = self.event('Notification', message='a\n\n  b ' + 'x' * 300)['claude.message']
        self.assertLessEqual(len(message), 60)
        self.assertTrue(message.startswith('a b x'))
        self.assertNotIn('\n', message)


class CodexAndGenericTests(unittest.TestCase):
    def test_a_finished_codex_turn_reports_idle_and_the_answer_start(self):
        updates = adapters.codex({'type': 'agent-turn-complete', 'cwd': '/work/app',
                                  'last-assistant-message': 'Done. All tests pass.'})
        self.assertEqual(updates, {'codex': 'idle', 'codex.message': 'Done. All tests pass.',
                                   'codex.project': 'app'})

    def test_other_codex_events_are_ignored_rather_than_invented(self):
        self.assertEqual(adapters.codex({'type': 'something-else'}), {})
        self.assertEqual(adapters.codex({}), {})

    def test_generic_adapter_validates_the_tool_name(self):
        self.assertEqual(adapters.generic('zcode', 'working', 'building'),
                         {'zcode': 'working', 'zcode.message': 'building'})
        for bad in ('', 'a b', 'x' * 33, 'a.b', 'a:b'):
            with self.assertRaises(ValueError):
                adapters.generic(bad, 'idle')

    def test_garbage_input_is_not_an_event(self):
        for text in ('', 'not json', '[1, 2]', '"text"', 'x' * (adapters.MAX_INPUT + 1)):
            self.assertEqual(adapters.parse_event(text), {})
        self.assertEqual(adapters.parse_event('{"a": 1}'), {'a': 1})


class HooksTests(unittest.TestCase):
    def test_the_hooks_block_covers_every_event_in_the_documented_shape(self):
        block = adapters.claude_hooks('run-me')['hooks']
        self.assertEqual(set(block), set(adapters.CLAUDE_EVENTS))
        for event, groups in block.items():
            self.assertEqual(groups[0]['hooks'], [{'type': 'command', 'command': 'run-me'}])
            self.assertEqual(groups[0].get('matcher'), '*' if event in ('PreToolUse', 'PostToolUse') else None)

    def test_the_command_quotes_both_paths(self):
        command = adapters.deckctl_command(Path('C:/Program Files/py/python.exe'), Path('C:/My Folder/deckctl.py'))
        self.assertTrue(command.startswith('"') and command.endswith(' adapter claude'))
        self.assertEqual(command.count('"'), 4)

    def test_deckctl_prints_the_block_without_needing_a_running_host(self):
        printed = io.StringIO()
        real, sys.stdout = sys.stdout, printed
        try:
            self.assertEqual(deckctl.main(['hooks', 'claude'], Path('missing.json')), 0)
        finally:
            sys.stdout = real
        self.assertIn('UserPromptSubmit', json.loads(printed.getvalue())['hooks'])


class BatchRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.daemon = Mock()
        self.daemon.config = {'profiles': {}}
        self.daemon.jobs.qsize.return_value = 0
        self.api = ControlServer(self.daemon, Path(self.temp.name) / 'api.json')
        self.api.start()
        self.addCleanup(self.api.stop)
        self.info = deckctl.load_info(Path(self.temp.name) / 'api.json')

    def post(self, data):
        return deckctl.call(self.info, 'POST', '/v1/vars', data)

    def test_variables_are_queued_together_in_one_atomic_submit(self):
        self.post({'set': {'claude': 'working', 'claude.tool': 'Bash'}})
        self.daemon.submit.assert_called_once_with(('var', 'claude', 'working'), ('var', 'claude.tool', 'Bash'))

    def test_bad_batches_are_rejected_whole(self):
        for bad in ({}, {'set': {}}, {'set': []}, {'set': {'bad name': 'x'}}, {'set': {'ok': True}},
                    {'set': {'ok': 'x' * 300}}, {'set': {f'v{i}': 'x' for i in range(21)}}):
            with self.assertRaises(deckctl.DeckctlError, msg=repr(bad)):
                self.post(bad)
        self.daemon.submit.assert_not_called()

    def test_a_full_queue_is_reported_as_busy(self):
        self.daemon.submit.side_effect = Busy('The host is busy: the action queue is full')
        with self.assertRaises(deckctl.DeckctlError) as raised:
            self.post({'set': {'a': 'b'}})
        self.assertIn('busy', str(raised.exception))

    def test_the_adapter_command_sends_the_updates_and_never_fails_the_tool(self):
        arguments = types.SimpleNamespace(command='adapter', name='claude', rest=[])
        event = json.dumps({'hook_event_name': 'Notification', 'message': 'Needs approval', 'cwd': '/work/app'})
        updates = deckctl.adapter_updates(arguments, io.StringIO(event))
        self.assertEqual(updates['claude'], 'waiting')
        deckctl.call(self.info, 'POST', '/v1/vars', {'set': updates})
        sent = {job[1]: job[2] for job in self.daemon.submit.call_args.args}
        self.assertEqual((sent['claude'], sent['claude.message']), ('waiting', 'Needs approval'))
        gone = Path(self.temp.name) / 'gone.json'
        self.assertEqual(deckctl.main(['adapter', 'claude'], gone), 0, 'a hook must exit 0 when the host is not running')
        self.assertEqual(deckctl.main(['adapter', 'generic', 'bad name', 'x'], gone), 1)


if __name__ == '__main__':
    unittest.main()
