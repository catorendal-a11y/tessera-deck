"""Small improvements to existing features: clearer reasons, missing reads and values that could not be set or seen."""
from datetime import datetime
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import action_preview
import ambient
import calendar_feed
import claude_setup
import deckctl
import diagnostics
import input_common
import pc_state
import plugins
import setup_tool
import substitution
import system_stats
import updates
import host_support
from control_api import ControlServer


class ProfileRuleTests(unittest.TestCase):
    def test_a_title_rule_with_nothing_after_it_matches_no_window(self):
        window = {'title': 'Notes - Editor', 'processes': ['editor.exe']}
        self.assertFalse(input_common.matches_foreground('title:', window))  # '' is in every title
        self.assertFalse(input_common.matches_foreground('title:   ', window))
        self.assertTrue(input_common.matches_foreground('title:notes', window))
        self.assertFalse(input_common.matches_foreground('process:', window))


class DiagnosticsTests(unittest.TestCase):
    def test_the_bundle_names_the_board_the_last_reset_and_the_plugins(self):
        status = {'running': True, 'device': {'connected': True, 'firmware': '1.2.2', 'protocol': 4, 'board': 'tessera-p4',
                                              'reset': 'task_wdt'},
                  'plugins': [{'id': 'obs', 'state': 'failed', 'error': 'stopped with code 1', 'crashes': 5, 'values': {'password': 'x'}}]}
        with tempfile.TemporaryDirectory() as folder:
            target = diagnostics.build(Path(folder), None, status, '1.2.2', Path(folder) / 'none.log')
            with zipfile.ZipFile(target) as archive:
                report = json.loads(archive.read('report.json'))
        self.assertEqual((report['host']['device']['board'], report['host']['device']['reset']), ('tessera-p4', 'task_wdt'))
        self.assertEqual(report['host']['plugins'], [{'id': 'obs', 'state': 'failed', 'error': 'stopped with code 1', 'crashes': 5}])


class UpdateCheckTests(unittest.TestCase):
    def failing(self, error):
        def opener(request, timeout=None):
            raise error
        return opener

    def test_each_failure_says_what_to_do(self):
        limited = urllib.error.HTTPError(updates.RELEASE_API, 403, 'rate limit exceeded', {}, None)
        broken = urllib.error.HTTPError(updates.RELEASE_API, 502, 'Bad Gateway', {}, None)
        offline = urllib.error.URLError('getaddrinfo failed')
        for error, words in ((limited, 'limiting requests'), (broken, 'HTTP 502'), (offline, 'could not be reached')):
            with self.subTest(words), self.assertRaises(ValueError) as raised:
                updates.check('1.0.0', opener=self.failing(error))
            self.assertIn(words, str(raised.exception))
            limited.close(), broken.close()


class UninstallTests(unittest.TestCase):
    def test_uninstall_takes_the_hooks_out_of_claude_code(self):
        with tempfile.TemporaryDirectory() as home:
            claude_setup.update(True, True, Path('python'), setup_tool.ROOT / 'host/deckctl.py', home=Path(home))
            self.assertEqual(claude_setup.state(Path(home)), {'events': True, 'permission': True})
            said = []
            self.assertTrue(setup_tool.forget_claude_hooks(Path(home), said.append))
            self.assertEqual(claude_setup.state(Path(home)), {'events': False, 'permission': False})
            self.assertIn('Claude Code', said[0])
            self.assertFalse(setup_tool.forget_claude_hooks(Path(home), said.append))  # nothing left to remove
            self.assertEqual(len(said), 1)

    def test_uninstalling_one_copy_leaves_the_hooks_of_another_copy(self):
        with tempfile.TemporaryDirectory() as home:
            other = Path('D:/new-tessera/host/deckctl.py')
            claude_setup.update(True, True, Path('python'), other, home=Path(home))
            said = []
            self.assertFalse(setup_tool.forget_claude_hooks(Path(home), said.append))
            self.assertEqual(claude_setup.state(Path(home), other), {'events': True, 'permission': True})
            self.assertEqual(said, [])


class DisplayTests(host_support.HostCase):
    def test_dimming_never_makes_the_panel_brighter(self):
        daemon = self.daemon()
        daemon.config['display'] = {'brightness': 100, 'dim_level': 10}
        daemon.wanted_brightness = lambda: 5  # quiet hours
        daemon.dim_display('after a test')
        daemon.panel.send_line.assert_called_with('AD_DISPLAY_DIM 5')
        daemon.wanted_brightness = lambda: 100
        daemon.dim_display('after a test')
        daemon.panel.send_line.assert_called_with('AD_DISPLAY_DIM 10')

    def test_the_music_key_says_when_nothing_plays(self):
        daemon = self.daemon()
        with patch.object(daemon.pc, 'snapshot', return_value=dict(pc_state.EMPTY)):
            self.assertEqual(daemon.live_content('media'), {'label': 'No music', 'sub': 'Nothing playing'})

    def test_a_failed_macro_names_the_step(self):
        daemon = self.daemon()
        key = daemon.config['profiles'][daemon.profile]['pages'][daemon.page][0]
        key['actions'] = [{'type': 'delay', 'ms': 1}, {'type': 'delay', 'ms': 1}, {'type': 'delay', 'ms': 1}]
        key.pop('states', None)
        with patch.object(daemon, 'run_action', side_effect=[None, ValueError('There is no such window'), None]):
            self.assertFalse(daemon.dispatch_press(key['id']))
        self.assertEqual(daemon.last_action['error'], 'Step 2: There is no such window')
        key['actions'] = [{'type': 'delay', 'ms': 1}]
        with patch.object(daemon, 'run_action', side_effect=ValueError('There is no such window')):
            daemon.dispatch_press(key['id'])
        self.assertEqual(daemon.last_action['error'], 'There is no such window')  # one step needs no number

    def test_a_web_request_names_the_environment_variable_that_is_not_set(self):
        daemon = self.daemon()
        with patch.dict(os.environ), self.assertRaises(Exception) as raised:
            os.environ.pop('TESSERA_TEST_MISSING', None)
            daemon.run_action({'type': 'http', 'url': '$(env:TESSERA_TEST_MISSING)', 'headers': {'X-Key': '$(env:TESSERA_TEST_MISSING)'}})
        self.assertIn('TESSERA_TEST_MISSING is not set', str(raised.exception))

    def test_a_file_rule_takes_a_path_in_the_home_folder_and_the_log_says_when_it_ran(self):
        daemon = self.daemon()
        with tempfile.TemporaryDirectory() as home:
            note = Path(home) / 'note.txt'
            note.write_text('one', encoding='utf-8')
            daemon.config['triggers'] = [{'when': {'type': 'file', 'path': '~/note.txt'}, 'actions': [{'type': 'delay', 'ms': 1}]}]
            with patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home}):
                daemon.trigger_tick(1)
                os.utime(note, ns=(1, 1))
                daemon.trigger_tick(2)
        self.assertEqual(daemon.jobs.get_nowait()[0], 'actions')
        self.assertIn('Automatic action 1 (file) ran', [call.args[0] for call in daemon.log.call_args_list])


class CalendarTests(unittest.TestCase):
    def event(self, start, end):
        return {'start': start, 'end': end, 'summary': 'Review', 'all_day': False}

    def test_the_meeting_key_follows_the_clock_format(self):
        today = [self.event(datetime(2026, 11, 13, 14, 30), datetime(2026, 11, 13, 15, 0))]
        tomorrow = [self.event(datetime(2026, 11, 14, 9, 0), datetime(2026, 11, 14, 10, 0))]
        before, during = datetime(2026, 11, 13, 13, 0), datetime(2026, 11, 13, 14, 45)
        self.assertEqual(calendar_feed.content(today, before, twelve=True)['sub'], '2:30 PM · in 1 h 30 min')
        self.assertEqual(calendar_feed.content(today, during, twelve=True)['sub'], 'Now · until 3:00 PM')
        self.assertEqual(calendar_feed.content(tomorrow, before, twelve=True)['sub'], 'Tomorrow 9:00 AM')
        self.assertEqual(calendar_feed.content(today, before)['sub'], '14:30 · in 1 h 30 min')


class WeatherTests(unittest.TestCase):
    def test_a_weather_line_that_cannot_be_refreshed_goes_after_an_hour(self):
        clock = [0.0]
        weather = ambient.Weather(clock=lambda: clock[0])
        settings = {'enabled': True, 'weather': {'latitude': 59.9, 'longitude': 10.7, 'name': 'Oslo'}}
        key = (59.9, 10.7, 'celsius', 'Oslo')
        weather._key = key
        with patch.object(ambient, '_get_json', return_value={'current': {}}), patch.object(ambient, 'describe', return_value='Oslo 4 C'):
            weather._refresh(key)
        weather._busy = True  # no refresh thread in this test: the network is "down" from here on
        clock[0] = 1800
        self.assertEqual(weather.line(settings), 'Oslo 4 C')
        clock[0] = ambient.STALE_SECONDS + 1
        self.assertEqual(weather.line(settings), '')


class ValueTextTests(unittest.TestCase):
    def test_uptime_under_an_hour_is_in_minutes(self):
        self.assertEqual(system_stats._format_gauge_text(42 * 60, {'fmt': 'uptime'}), '42m')
        self.assertEqual(system_stats._format_gauge_text(3 * 3600 + 5, {'fmt': 'uptime'}), '3h')
        self.assertEqual(system_stats._format_gauge_text(2 * 86400, {'fmt': 'uptime'}), '2d')

    def test_a_counter_or_timer_nobody_has_used_yet_shows_its_start_value(self):
        text = substitution.substitute('$(counter:laps) $(timer:tea) $(timer-state:tea) [$(var:x)] $(other)', {})
        self.assertEqual(text, '0 00:00 IDLE [] $(other)')
        self.assertEqual(substitution.substitute('$(counter:laps)', {'counter:laps': '7'}), '7')


class DryRunTests(unittest.TestCase):
    STEP = [{'type': 'plugin', 'plugin': 'obs', 'command': 'record'}]

    def text(self, known):
        result = action_preview.preview(self.STEP, {}, plugins=known)
        return result['ok'], result['steps'][0]['text']

    def test_a_plugin_step_says_when_its_plugin_cannot_take_it(self):
        self.assertEqual(self.text([]), (False, 'The plugin obs is not installed: put its folder in the plugins folder'))
        off = [{'id': 'obs', 'name': 'OBS Studio', 'enabled': False, 'state': 'disabled'}]
        self.assertEqual(self.text(off), (False, 'OBS Studio is off: turn it on in More → Plugins'))
        failed = [{'id': 'obs', 'name': 'OBS Studio', 'enabled': True, 'state': 'failed'}]
        self.assertEqual(self.text(failed), (False, 'Plugin stopped: turn it off and on in More → Plugins (OBS Studio)'))
        running = [{'id': 'obs', 'name': 'OBS Studio', 'enabled': True, 'state': 'running'}]
        self.assertTrue(self.text(running)[0])
        self.assertTrue(self.text(None)[0])  # the host is not running: nothing is known about the plugins


class ControlTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.daemon = Mock()
        self.daemon.config = {'profiles': {'main': {'pages': {'home': [], 'tools': []}}, 'work': {'pages': {'start': []}}}}
        self.daemon.events = plugins.EventLog()
        self.daemon.jobs.qsize.return_value = 0
        self.daemon.jobs.maxsize = 64
        for name, value in (('profile', 'main'), ('page', 'home'), ('panel', None), ('dimmed', False), ('locked', False),
                            ('custom_vars', {'claude': 'idle'}), ('agents', {}), ('dropped_jobs', 0), ('slow_running', []),
                            ('profile_locked', True)):
            setattr(self.daemon, name, value)
        self.daemon.log = Mock()
        self.info = Path(temp.name) / 'api.json'
        self.api = ControlServer(self.daemon, self.info)
        self.api.start()
        self.addCleanup(self.api.stop)

    def call(self, method, path, data=None):
        request = urllib.request.Request(f'http://127.0.0.1:{self.api.server.server_port}{path}', method=method,
                                         data=None if data is None else json.dumps(data).encode(),
                                         headers={'Content-Type': 'application/json', 'X-Deck-Token': self.api.token})
        try:
            with urllib.request.urlopen(request, timeout=3) as reply:
                return reply.status, json.loads(reply.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_the_state_lists_the_profiles_and_the_profile_lock(self):
        status, state = self.call('GET', '/v1/state')
        self.assertEqual(status, 200)
        self.assertEqual(state['profiles'], {'main': ['home', 'tools'], 'work': ['start']})
        self.assertIs(state['profile_locked'], True)

    def test_an_unknown_profile_or_page_is_answered_with_the_names_that_exist(self):
        self.assertEqual(self.call('POST', '/v1/page', {'profile': 'nope'}), (400, {'error': 'Unknown profile: nope. Profiles: main, work'}))
        self.assertEqual(self.call('POST', '/v1/page', {'profile': 'main', 'page': 'nope'}),
                         (400, {'error': 'Unknown page: nope. Pages of main: home, tools'}))

    def test_deckctl_reads_one_variable(self):
        printed = io.StringIO()
        with redirect_stdout(printed):
            self.assertEqual(deckctl.main(['get', 'claude'], self.info), 0)
        self.assertEqual(printed.getvalue().strip(), 'idle')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(deckctl.main(['get', 'never-set'], self.info), 1)

    def test_every_deckctl_command_says_what_it_does(self):
        listed = deckctl.build_parser().format_help()
        for words in ('press a key', 'flash a key green', 'flash a key red', 'wake the panel', 'dim the panel',
                      'print what the host knows', 'print one variable'):
            self.assertIn(words, listed)

    def test_deckctl_says_how_to_start_a_host_that_is_not_running(self):
        with self.assertRaises(deckctl.DeckctlError) as raised:
            deckctl.load_info(self.info.with_name('missing.json'))
        self.assertIn('Start it from the tray icon', str(raised.exception))


class EditorTests(unittest.TestCase):
    """The editor's own functions, run in node (tests/test_editor.py has the stand-in for the page)."""

    def run_editor(self, script):
        from test_editor import run_editor
        return run_editor(self, script)

    def test_steps_the_host_would_refuse_stay_drafts_with_a_reason(self):
        found = self.run_editor(r"""
const result = {};
hostRules = {keys: ['ctrl', 'shift', 't'], platform: 'win32', scripts: ['.py', '.js']};
result.typo = valueProblem({type: 'hotkey', keys: 'ctrl+shfit+t'});
result.keys = valueProblem({type: 'hotkey', keys: 'Ctrl + Shift + T'});
result.focus = valueProblem({type: 'window', op: 'focus', process: ' '});
result.focused = valueProblem({type: 'window', op: 'focus', process: 'notepad.exe'});
result.close = valueProblem({type: 'window', op: 'close'});
result.moveto = valueProblem({type: 'mouse', op: 'moveto'});
result.moved = valueProblem({type: 'mouse', op: 'moveto', x: 0, y: 10});
result.shell = valueProblem({type: 'script', path: 'C:\\tools\\run.sh'});
hostRules = {platform: 'linux', scripts: ['.py', '.sh']};
result.linux = valueProblem({type: 'script', path: '/home/me/run.sh'});
result.relative = valueProblem({type: 'script', path: 'run.sh'});
result.unknown = valueProblem({type: 'hotkey', keys: 'ctrl+shfit+t'});  // no key list from the host: not checked
return result;
""")
        self.assertEqual(found, {
            'typo': 'use key names such as ctrl+shift+t: “shfit” is not one', 'keys': '',
            'focus': 'fill in the process name of the program to bring to the front', 'focused': '', 'close': '',
            'moveto': 'type the Screen X and Screen Y to move the pointer to', 'moved': '',
            'shell': 'use a .py or .js file', 'linux': '', 'relative': 'use the full path of the script file', 'unknown': ''})

    def test_deleting_a_page_or_profile_says_which_keys_lost_a_step(self):
        found = self.run_editor(r"""
const fresh = () => ({default_profile: 'Main', profiles: {
  Main: {match: [], pages: {First: [{id: 3, label: 'Media', icon: 'ok', actions: [{type: 'folder', page: 'Media'}]},
                                    {id: 9, label: 'Both', icon: 'ok', actions: [{type: 'page', page: 'Media'}, {type: 'delay', ms: 1}]},
                                    {id: 4, label: 'Work', icon: 'ok', actions: [{type: 'profile', profile: 'Work'}]}],
                            Media: [{id: 1, label: 'Play', icon: 'ok', actions: []}, {id: 2, label: 'Next', icon: 'ok', actions: []}]}},
  Work: {match: [], pages: {Start: [{id: 1, label: 'Mail', icon: 'ok', actions: []}]}}}});
const said = () => String(document.querySelector('#toast').textContent);
const result = {};
config = fresh(); profile = 'Main'; page = 'Media'; selected = 1;
deletePage(); result.page = said();
config = fresh(); profile = 'Work'; page = 'Start'; selected = 1;
deleteProfile(); result.profile = said();
config = fresh(); profile = 'Main'; page = 'First'; selected = 1; config.profiles.Main.pages.Empty = [];
page = 'Empty'; deletePage(); result.plain = said();
return result;
""")
        self.assertEqual(found, {
            'page': 'Page “Media” was deleted with its 2 keys. 2 keys lost the step that opened it: First 3, First 9.',
            'profile': 'Profile “Work” was deleted with its 1 key. 1 key lost the step that switched to it: Main First 4.',
            'plain': 'Page “Empty” was deleted.'})

    def test_a_full_page_says_what_to_do(self):
        found = self.run_editor(r"""
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: Array.from({length: 18}, (_, i) => ({id: i + 1, label: 'K', icon: 'ok', actions: []}))}}}};
profile = 'Main'; page = 'First'; selected = 1;
addAction('delay');
return String(document.querySelector('#toast').textContent);
""")
        self.assertEqual(found, 'This page has all 18 keys. Put the action on a new page (＋ beside the page tabs), or drop it on a key to add a step.')

    def test_an_unused_counter_or_timer_shows_its_start_value_on_the_tile(self):
        found = self.run_editor(r"""
dashboard = {variables: {'counter:laps': '7'}};
return [expandLabel('$(counter:laps)'), expandLabel('$(counter:new) $(timer:tea) $(timer-state:tea)')];
""")
        self.assertEqual(found, ['7', '0 00:00 IDLE'])

    def test_a_file_that_is_not_an_export_says_that_nothing_changed(self):
        found = self.run_editor(r"""
try { await importConfig({size: 8, name: 'notes.json', text: async () => 'Not json'}); return 'imported'; }
catch (error) { return error.message; }
""")
        self.assertEqual(found, 'This file is not a Tessera export (it is not valid JSON). Nothing was changed.')


if __name__ == '__main__':
    unittest.main()
