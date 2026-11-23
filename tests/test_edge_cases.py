"""Edge cases found by reading the code, on both systems. Each test failed before its fix."""
import json
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import calendar_feed
import config_store
import control_api
import deck_control
import diagnostics
import import_review
import plugins
import host_support
from platform_linux import audio as linux_audio
from platform_linux import autostart as linux_autostart
from platform_linux import media as linux_media
from platform_linux import session as linux_session


def launch_key(number):
    return {'id': 1, 'label': f'Tool {number}', 'actions': [{'type': 'open', 'target': f'C:/tools/tool{number}.exe'}]}


class ImportReviewTests(unittest.TestCase):
    def test_a_long_file_lists_its_commands_first_and_says_how_many_it_left_out(self):
        pages = {f'page {number}': [launch_key(number)] for number in range(250)}
        pages['last'] = [{'id': 1, 'label': 'Clean', 'actions': [{'type': 'shell', 'command': 'del /s /q C:\\data'}]}]
        findings = import_review.review({'profiles': {'main': {'pages': pages}}})
        details = [finding['detail'] for finding in findings]
        self.assertIn('runs the command: del /s /q C:\\data', details)  # after 250 launches in the file, still listed
        self.assertEqual(len(findings), import_review.MAX_LISTED + 1)
        self.assertEqual(findings[-1]['risk'], 'high')
        self.assertIn('51 more', findings[-1]['detail'])

    def test_a_short_file_gets_no_note_about_more(self):
        findings = import_review.review({'profiles': {'main': {'pages': {'main': [launch_key(1)]}}}})
        self.assertEqual([finding['kind'] for finding in findings], ['open'])


class DiagnosticsTests(unittest.TestCase):
    def test_a_linux_home_folder_loses_the_user_name(self):
        cleaned = diagnostics.clean('The script was not found: /home/alice/bin/build.sh')
        self.assertNotIn('alice', cleaned)
        self.assertIn('/home/<user>/bin/build.sh', cleaned)


class ConfigStoreTests(unittest.TestCase):
    def test_a_file_nested_too_deep_is_refused_like_any_unreadable_file(self):
        with self.assertRaises(ValueError):
            config_store.check(b'[' * 100000 + b']' * 100000)


class EventLogTests(unittest.TestCase):
    def test_an_id_from_before_a_host_restart_starts_from_the_beginning(self):
        log = plugins.EventLog()
        log.add('press', button=1)
        events, last = log.since(500, with_last=True)  # 500 is from the host that ran before
        self.assertEqual([event['id'] for event in events], [1])
        self.assertEqual(last, 1)


class TokenFileTests(unittest.TestCase):
    def test_the_file_is_private_before_the_token_is_in_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path, seen = Path(folder) / 'deck-api.local.tmp', []
            with patch.object(control_api, 'make_private', lambda target: seen.append(Path(target).read_text(encoding='utf-8'))):
                control_api.write_private(path, '{"token": "secret"}')
            self.assertEqual(seen, [''])
            self.assertEqual(path.read_text(encoding='utf-8'), '{"token": "secret"}')


class LinuxSideTests(unittest.TestCase):
    """The Linux modules import on any system, and these parts need no sound server, bus or display."""

    def test_volume_up_never_lowers_a_level_above_100(self):
        calls = []
        linux_audio._apply(lambda *args: calls.append(args), 'sink', 'SINK', 'up', None, 5, 120)
        self.assertEqual(calls, [('set-sink-volume', 'SINK', '120%')])
        calls.clear()
        linux_audio._apply(lambda *args: calls.append(args), 'sink', 'SINK', 'up', None, 5, 98)
        self.assertEqual(calls, [('set-sink-volume', 'SINK', '100%')])
        calls.clear()
        linux_audio._apply(lambda *args: calls.append(args), 'sink', 'SINK', 'down', None, 5, 120)
        self.assertEqual(calls, [('set-sink-volume', 'SINK', '100%')])

    def test_a_player_reports_shuffle_and_repeat(self):
        playing = linux_media.describe({'Shuffle': ('b', True), 'LoopStatus': ('s', 'Playlist')})
        self.assertEqual((playing['shuffle'], playing['repeat']), (True, 'list'))
        one = linux_media.describe({'Shuffle': ('b', False), 'LoopStatus': ('s', 'Track')})
        self.assertEqual((one['shuffle'], one['repeat']), (False, 'track'))
        self.assertEqual(linux_media.describe({'LoopStatus': ('s', 'None')})['repeat'], 'none')
        silent = linux_media.describe({})  # a player that offers neither
        self.assertEqual((silent['shuffle'], silent['repeat']), (None, ''))
        self.assertEqual((linux_media.EMPTY['shuffle'], linux_media.EMPTY['repeat']), (None, ''))

    def test_the_session_says_how_long_the_pc_has_been_idle(self):
        self.assertIsInstance(linux_session.idle_seconds(), float)  # the idle clock asks every second

    def test_an_autostart_entry_for_another_folder_does_not_count(self):
        with tempfile.TemporaryDirectory() as folder:
            here, elsewhere = Path(folder) / 'tessera-new', Path(folder) / 'tessera-old'
            entry = Path(folder) / 'tessera.desktop'
            entry.write_text(f'[Desktop Entry]\nExec=python "{elsewhere / "host/tessera_tray.py"}"\n', encoding='utf-8')
            self.assertFalse(linux_autostart.is_enabled(entry, here))
            self.assertTrue(linux_autostart.is_enabled(entry, elsewhere))
            self.assertFalse(linux_autostart.is_enabled(Path(folder) / 'missing.desktop', here))


    def test_with_the_arch_package_the_entry_starts_the_wrapper_and_is_found_again(self):
        # /usr/bin/tessera syncs the copy after a package update and sets TESSERA_PACKAGED; the copy's own python does neither
        with tempfile.TemporaryDirectory() as folder:
            data, entry = Path(folder) / 'data', Path(folder) / 'tessera.desktop'
            with patch.dict('os.environ', {'TESSERA_PACKAGED': '1'}):
                linux_autostart.enable(entry, data)
                self.assertIn('Exec="tessera" "--tray"', entry.read_text(encoding='utf-8'))
                self.assertTrue(linux_autostart.is_enabled(entry, data))

    def test_an_arch_entry_from_before_the_wrapper_counts_and_is_rewritten_to_it(self):
        # an entry written by 1.2.11 or older starts the copy's python, so the tray it starts has no TESSERA_PACKAGED
        with tempfile.TemporaryDirectory() as folder:
            data, entry = Path(folder) / 'data', Path(folder) / 'tessera.desktop'
            data.mkdir()
            (data / '.pkgrel').write_text('1\n', encoding='utf-8')  # the launcher copies it in with the package
            old = f'[Desktop Entry]\nExec="{data / "host/.venv/bin/python"}" "{data / "host/tessera_tray.py"}"\n'
            for packaged in ({'TESSERA_PACKAGED': '1'}, {}):
                entry.write_text(old, encoding='utf-8')
                with patch.dict('os.environ', packaged):
                    if not packaged:
                        os.environ.pop('TESSERA_PACKAGED', None)
                    self.assertTrue(linux_autostart.is_enabled(entry, data))
                    self.assertIn('Exec="tessera" "--tray"', entry.read_text(encoding='utf-8'))
                    entry.unlink()
                    linux_autostart.enable(entry, data)  # Start with the desktop turned on from that tray
                    self.assertIn('Exec="tessera" "--tray"', entry.read_text(encoding='utf-8'))


class AutostartTests(unittest.TestCase):
    def test_start_with_the_desktop_writes_the_entry_on_linux(self):
        with tempfile.TemporaryDirectory() as folder:
            module = Mock()
            module.startup_script_path.return_value = Path(folder) / 'tessera.desktop'
            with patch.object(deck_control, 'IS_WINDOWS', False), patch.object(deck_control, 'load', return_value=module):
                deck_control.set_autostart(True)  # the tray passes no folder
            module.enable.assert_called_once_with(Path(folder) / 'tessera.desktop', deck_control.ROOT)


def ics(*events):
    body = ''.join('BEGIN:VEVENT\r\n' + '\r\n'.join(lines) + '\r\nEND:VEVENT\r\n' for lines in events)
    return 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + body + 'END:VCALENDAR\r\n'


class CalendarTests(unittest.TestCase):
    NOW = datetime(2026, 11, 13, 8, 0)
    GOOD = ['UID:good', 'DTSTART:20261113T093000', 'DTEND:20261113T100000', 'SUMMARY:Design review']

    def summaries(self, *events):
        return [event['summary'] for event in calendar_feed.upcoming(ics(*events), self.NOW)]

    def test_an_event_from_before_1970_is_dropped_alone(self):
        ancient = ['UID:old', 'DTSTART:19600101T090000Z', 'DTEND:19600101T100000Z', 'SUMMARY:Ancient']
        self.assertEqual(self.summaries(ancient, self.GOOD), ['Design review'])

    def test_an_event_with_an_impossible_length_is_dropped_alone(self):
        endless = ['UID:long', 'DTSTART:20261113T090000', 'DURATION:P999999999999D', 'SUMMARY:Endless']
        self.assertEqual(self.summaries(endless, self.GOOD), ['Design review'])

    def test_an_event_that_ends_past_the_last_year_is_dropped_alone(self):
        late = ['UID:late', 'DTSTART:20261113T090000', 'DURATION:P2915000D', 'SUMMARY:Late']
        self.assertEqual(self.summaries(late, self.GOOD), ['Design review'])


class DaemonTests(host_support.HostCase):
    def test_a_page_the_panel_refuses_at_connect_does_not_look_like_a_lost_link(self):
        daemon = self.daemon()
        daemon.push_page = Mock(side_effect=ValueError('The button layout is too large'))
        daemon.push_first_page()  # raising here made the host close and reopen the port for ever
        self.assertIn('too large', daemon.log.call_args.args[0])

    def test_a_profile_whose_page_the_panel_refuses_leaves_the_host_on_the_old_one(self):
        daemon = self.daemon()
        other = next(name for name in daemon.config['profiles'] if name != daemon.profile)
        daemon.folder_stack.append('status')
        before = (daemon.profile, daemon.page, list(daemon.folder_stack))
        daemon.push_page = Mock(side_effect=ValueError('The button layout is too large'))
        with self.assertRaises(ValueError):
            daemon.switch_profile(other)
        self.assertEqual((daemon.profile, daemon.page, list(daemon.folder_stack)), before)


class TrayTests(unittest.TestCase):
    def setUp(self):
        try:
            import tessera_tray
        except ImportError:
            self.skipTest('pystray is not installed')
        self.tray = tessera_tray

    def test_save_diagnostics_opens_the_folder_with_the_systems_own_opener(self):
        app = host_support.tray_app(Mock())
        app.icon, app.background = Mock(), lambda work: work()
        saved = Path('reports') / 'tessera-diagnostics.zip'
        with patch('setup_tool.diagnostics', return_value=saved), patch.object(self.tray, 'IS_WINDOWS', False), \
                patch.object(self.tray, 'open_path') as open_path, patch.object(self.tray.subprocess, 'Popen') as popen:
            app.save_diagnostics()
        open_path.assert_called_once_with(saved.parent)
        popen.assert_not_called()  # there is no explorer on Linux
        self.assertIn('Saved tessera-diagnostics.zip', app.icon.notify.call_args.args[0])

    def first_run(self, folder, record):
        path = Path(folder) / 'tray-first-run.local.json'
        if record is not None:
            path.write_text(json.dumps(record), encoding='utf-8')
        return path

    def test_a_first_run_record_copied_from_another_folder_still_asks_about_autostart(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'Tessera.vbs'
            script.write_text('a copy in another folder', encoding='utf-8')
            cases = (({'asked': 'autostart', 'root': 'C:/tessera-old'}, False),  # copied over with the *.local.json files
                     ({'asked': 'autostart', 'root': str(self.tray.ROOT)}, True),  # this folder was asked
                     (None, False))  # never asked
            for record, asked in cases:
                with self.subTest(record=record), patch.object(self.tray, 'FIRST_RUN_PATH', self.first_run(folder, record)), \
                        patch.object(self.tray, 'startup_script_path', return_value=script), \
                        patch.object(self.tray, 'autostart_enabled', return_value=False):
                    self.assertEqual(host_support.tray_app(Mock()).asked_autostart, asked)
                (Path(folder) / 'tray-first-run.local.json').unlink(missing_ok=True)

    def test_a_first_run_record_counts_when_nothing_starts_another_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.first_run(folder, {'asked': 'autostart'})  # written by a version before the folder was recorded
            with patch.object(self.tray, 'FIRST_RUN_PATH', path), \
                    patch.object(self.tray, 'startup_script_path', return_value=Path(folder) / 'missing.vbs'), \
                    patch.object(self.tray, 'autostart_enabled', return_value=False):
                self.assertTrue(host_support.tray_app(Mock()).asked_autostart)


class EditorTests(unittest.TestCase):
    """The editor's own functions, run in node (tests/test_editor.py has the stand-in for the page)."""

    def run_editor(self, script):
        from test_editor import run_editor
        return run_editor(self, script)

    def test_deleting_a_page_drops_a_rail_shortcut_left_without_steps(self):
        found = self.run_editor(r"""
const fresh = () => ({default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [], Second: []}}, Other: {match: [], pages: {Home: []}}},
  panel: {shortcuts: [{type: 'actions', label: 'Go', icon: 'ok', actions: [{type: 'page', page: 'Second'}]},
                      {type: 'actions', label: 'Both', icon: 'ok', actions: [{type: 'page', page: 'Second'}, {type: 'delay', ms: 5}]},
                      {type: 'actions', label: 'Work', icon: 'ok', actions: [{type: 'profile', profile: 'Other'}]}]}});
const result = {};
config = fresh(); profile = 'Main'; page = 'Second'; selected = 1;
changePage(null);
result.page = config.panel.shortcuts.map(s => [s.label, s.actions.length]);
config = fresh(); profile = 'Other'; page = 'Home'; selected = 1;
deleteProfile();
result.profile = config.panel.shortcuts.map(s => s.label);
return result;
""")
        # a shortcut with no steps makes the host refuse every save
        self.assertEqual(found, {'page': [['Both', 1], ['Work', 1]], 'profile': ['Go', 'Both']})

    def test_a_key_made_after_clear_gets_its_step_on_pressed(self):
        found = self.run_editor(r"""
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [
  {id: 1, label: 'X', icon: 'ok', actions: [], hold_actions: [{type: 'delay', ms: 1}]},
  {id: 2, label: 'Mic', icon: 'ok', actions: [], states: [{label: 'Off', actions: []}, {label: 'On', actions: []}]}]}}}};
profile = 'Main'; page = 'First'; selected = 1; editState = 0;
syncEditList(); editList = 'hold_actions';  // the Held tab is open on key 1
clearButton();
addAction('delay');  // a click in the action list makes a new key on the selected, now empty, slot
const key = config.profiles.Main.pages.First.find(b => b.id === 1);
const result = {pressed: (key.actions || []).length, held: (key.hold_actions || []).length};
editState = 1;  // "Edit state 2" was open on another key
addAction('delay', 2);  // a drop on key 2
const toggle = config.profiles.Main.pages.First.find(b => b.id === 2);
result.states = toggle.states.map(state => state.actions.length);
return result;
""")
        self.assertEqual(found, {'pressed': 1, 'held': 0, 'states': [1, 0]})

    def test_the_toasts_undo_takes_back_only_the_change_it_is_about(self):
        found = self.run_editor(r"""
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [
  {id: 1, label: 'One', icon: 'ok', actions: []}, {id: 2, label: 'Two', icon: 'ok', actions: []}]}}}};
profile = 'Main'; page = 'First'; selected = 1;
const labels = () => config.profiles.Main.pages.First.map(b => b.label);
clearButton();  // the toast offers Undo for this
const about = history[history.length - 1];
mutate(() => { config.profiles.Main.pages.First[0].label = 'Renamed'; });  // a later edit, with no toast
undoIf(about);
const later = labels();
selected = 2; clearButton();
undoIf(history[history.length - 1]);
return {later, undone: labels()};
""")
        self.assertEqual(found, {'later': ['Renamed'], 'undone': ['Renamed']})

    def test_a_second_save_during_a_conflict_waits_for_the_merge(self):
        found = self.run_editor(r"""
const fresh = () => ({default_profile: 'Main', profiles: {Main: {match: [], pages: {First: []}}}});
config = fresh(); savedBase = clone(config); revision = 'r1'; dirty = true; conflicted = false;
let merge = null;
const sent = [];
api = async (path, data) => {
  if (!data) { await new Promise(done => { merge = done; }); return {config: {...fresh(), display: {brightness: 40}}, revision: 'r2'}; }
  sent.push(data.revision);
  if (sent.length === 1) throw Object.assign(new Error('Changed elsewhere'), {status: 409});
  return {revision: 'r3'};
};
const first = save();
await settle();  // the first save was refused and now reads the file to merge
let second = 'ok';
const waiting = save().catch(error => { second = error.status; });  // Ctrl+S meanwhile
await settle();
merge();
await first; await waiting; await settle();
return {second, sent, dirty};
""")
        self.assertEqual(found, {'second': 'ok', 'sent': ['r1', 'r2'], 'dirty': False})


if __name__ == '__main__':
    unittest.main()
