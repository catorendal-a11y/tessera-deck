"""The terminal editor: saves made in other windows, page renames, import review, export and Stop host."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import host_support  # noqa: E402

HAS_TEXTUAL = importlib.util.find_spec('textual') is not None
if HAS_TEXTUAL:
    import tessera_terminal
    from deck_forms import ActionForm
    from tessera_terminal import DeckPane, TesseraApp
    from textual.widgets import Button, Input, Select

DENIED = PermissionError(13, 'Access is denied')


def config():
    return {'default_profile': 'Main', 'profiles': {'Main': {'match': [], 'pages': {
        'First': [{'id': 1, 'label': 'Copy', 'icon': 'ok', 'actions': [{'type': 'hotkey', 'keys': 'ctrl+c'}]}],
        'Second': [{'id': 2, 'label': 'Back', 'icon': 'ok', 'actions': [{'type': 'page', 'page': 'First'}],
                    'hold_actions': [{'type': 'page', 'page': 'First'}],
                    'double_actions': [{'type': 'folder', 'page': 'First'}]}]}}}}


def risky():
    data = config()
    data['profiles']['Main']['pages']['First'].append(
        {'id': 3, 'label': 'Run', 'icon': 'ok', 'actions': [{'type': 'shell', 'command': 'calc'}]})
    data['triggers'] = [{'when': {'type': 'interval', 'seconds': 10}, 'actions': [{'type': 'shell', 'command': 'calc'}]}]
    data['plugins'] = {'home-assistant': {'enabled': True, 'settings': {'url': 'http://attacker.invalid'}}}
    return data


@unittest.skipIf(not HAS_TEXTUAL, 'textual is not installed')
class TerminalAppTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.path = self.folder / 'profiles.json'
        self.write(config())
        # the app reads the host log and writes commands next to ROOT: keep them in the test folder
        for name, value in (('ROOT', self.folder), ('STOPPED_PATH', self.folder / 'deck-stopped.local.json')):
            patcher = patch.object(tessera_terminal, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, data, path=None):
        (path or self.path).write_text(json.dumps(data), encoding='utf-8')

    def saved(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def app(self):
        return TesseraApp(controller=Mock(), profile_path=self.path)

    @staticmethod
    def status(app):
        return str(app.query_one(DeckPane).query_one('#deck-state').content)

    @staticmethod
    async def press(pilot, button):
        button.press()
        await pilot.pause()
        await pilot.pause()

    async def form(self, pilot, app, opener, **values):
        await self.press(pilot, app.query_one(DeckPane).query_one('#' + opener, Button))
        for name, value in values.items():
            app.screen.query_one('#field-' + name).value = value
        await self.press(pilot, app.screen.query_one('#submit', Button))

    async def edit_slot(self, pilot, app, label):
        await self.press(pilot, app.query_one(DeckPane).query_one('#deck-slot-1', Button))
        app.screen.query_one('#button-label', Input).value = label
        await self.press(pilot, app.screen.query_one('#button-save', Button))

    async def test_a_save_made_in_another_window_is_kept_and_the_change_is_asked_for_again(self):
        app = self.app()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()
            other = config()
            other['profiles']['Main']['pages']['EditorPage'] = []
            self.write(other)  # the graphical editor saves while the terminal is open
            await self.edit_slot(pilot, app, 'Changed')
            pages = self.saved()['profiles']['Main']['pages']
            self.assertIn('EditorPage', pages)
            self.assertEqual(pages['First'][0]['label'], 'Copy')
            self.assertIn('another window', self.status(app))
            await self.edit_slot(pilot, app, 'Changed')
            pages = self.saved()['profiles']['Main']['pages']
            self.assertIn('EditorPage', pages)
            self.assertEqual(pages['First'][0]['label'], 'Changed')

    async def test_renaming_a_page_keeps_its_place_and_points_every_action_and_shortcut_at_it(self):
        data = config()
        data['panel'] = {'shortcuts': [{'profile': 'Main', 'page': 'First', 'icon': 'lc:e0ff'}]}
        self.write(data)
        app = self.app()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()
            await self.form(pilot, app, 'page-edit', name='Home')
            saved = self.saved()
            pages = saved['profiles']['Main']['pages']
            self.assertEqual(list(pages), ['Home', 'Second'])  # the first page is the one the panel opens
            key = pages['Second'][0]
            self.assertEqual([key[name][0]['page'] for name in ('actions', 'hold_actions', 'double_actions')], ['Home'] * 3)
            self.assertEqual(saved['panel']['shortcuts'][0]['page'], 'Home')
            self.assertEqual(app.query_one(DeckPane).query_one('#deck-page', Select).value, 'Home')

    async def test_a_rename_that_cannot_be_saved_keeps_the_page_and_the_app_running(self):
        app = self.app()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()
            with patch.object(tessera_terminal, 'save_profiles', side_effect=DENIED):
                await self.form(pilot, app, 'page-edit', name='Home')
            pane = app.query_one(DeckPane)
            self.assertEqual((pane.page, pane.query_one('#deck-page', Select).value), ('First', 'First'))
            self.assertIn('Not saved', self.status(app))
            await self.edit_slot(pilot, app, 'Still works')
            self.assertEqual(self.saved()['profiles']['Main']['pages']['First'][0]['label'], 'Still works')

    async def test_import_lists_commands_and_automatic_rules_and_leaves_them_out_unless_kept(self):
        local = config()
        local['plugins'] = {'obs': {'enabled': False, 'settings': {'host': 'localhost'}}}
        self.write(local)
        source = self.folder / 'shared.json'
        self.write(risky(), source)
        app = self.app()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()
            await self.form(pilot, app, 'deck-import', path=str(source))
            self.assertIsInstance(app.screen, ActionForm)
            self.assertIn('runs the command: calc', app.screen.note)
            self.assertIn('Automatic rule', app.screen.note)
            self.assertEqual(self.saved(), local, 'nothing is saved before the choice')
            await self.press(pilot, app.screen.query_one('#submit', Button))  # Keep these actions: No
            saved = self.saved()
            self.assertEqual(saved['triggers'], [])
            self.assertNotIn('shell', json.dumps(saved))
            self.assertEqual(saved['plugins'], local['plugins'], 'the plugins set up here stay')
            self.assertEqual(self.status(app), 'Imported')
            await self.form(pilot, app, 'deck-import', path=str(source))
            app.screen.query_one('#field-keep', Select).value = True
            await self.press(pilot, app.screen.query_one('#submit', Button))
            self.assertEqual(self.saved()['triggers'], risky()['triggers'])

    async def test_an_import_that_cannot_be_saved_changes_nothing_and_says_so(self):
        app = self.app()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()
            for profile in ('Main', 'Streaming'):
                source = self.folder / f'{profile}.json'
                self.write({'default_profile': profile, 'profiles': {profile: {'match': [], 'pages': {'Live': []}}}}, source)
                with patch.object(tessera_terminal, 'save_profiles', side_effect=DENIED):
                    await self.form(pilot, app, 'deck-import', path=str(source))
                pane = app.query_one(DeckPane)
                self.assertEqual((pane.profile, pane.page), ('Main', 'First'))
                self.assertEqual(pane.query_one('#deck-profile', Select).value, 'Main')
                self.assertIn('Not saved', self.status(app))
                self.assertEqual(self.saved(), config())

    async def test_export_leaves_out_the_calendar_address_and_codes_and_hides_credentials(self):
        data = config()
        data['calendar'] = {'url': 'https://calendar.example.invalid/private-abc/basic.ics'}
        data['profiles']['Main']['pages']['First'] += [
            {'id': 3, 'label': 'Hook', 'icon': 'ok', 'actions': [{'type': 'http', 'url': 'https://example.invalid/hook',
                                                                  'method': 'POST', 'headers': {'Authorization': 'Bearer secret123'}}]},
            {'id': 4, 'label': 'Alarm', 'icon': 'ok', 'actions': [{'type': 'homeassistant', 'action': 'alarm_control_panel.alarm_disarm',
                                                                   'entity_id': 'alarm_control_panel.home', 'data': {'code': '4321'}}]}]
        self.write(data)
        target = self.folder / 'export.json'
        app = self.app()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()
            await self.form(pilot, app, 'deck-export', path=str(target))
            status = self.status(app)
        text = target.read_text(encoding='utf-8')
        for secret in ('private-abc', 'secret123', '4321'):
            self.assertNotIn(secret, text)
        keys = json.loads(text)['profiles']['Main']['pages']['First']
        self.assertEqual(keys[1]['actions'][0]['headers']['Authorization'], '$(env:TESSERA_AUTHORIZATION)')
        self.assertIn('the calendar address', status)
        self.assertIn('$(env:TESSERA_AUTHORIZATION)', status)

    async def test_stop_host_tells_the_tray_and_start_host_takes_it_back(self):
        marker = tessera_terminal.STOPPED_PATH
        app = self.app()
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause()
            pane = app.query_one(DeckPane)
            await self.press(pilot, pane.query_one('#deck-host-stop', Button))
            await app.workers.wait_for_complete()
            self.assertTrue(marker.exists())
            app.controller.stop.assert_called_once()
            await self.press(pilot, pane.query_one('#deck-host-start', Button))
            await app.workers.wait_for_complete()
            self.assertFalse(marker.exists())
            app.controller.start.assert_called_once()


@unittest.skipIf(importlib.util.find_spec('pystray') is None, 'pystray is not installed')
class TrayTerminalStopTests(unittest.TestCase):
    def setUp(self):
        import tessera_tray
        self.tray = tessera_tray
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.marker = Path(folder.name) / 'deck-stopped.local.json'
        for name, value in (('STOPPED_PATH', self.marker), ('PROFILES_PATH', Path(folder.name) / 'profiles.json'),
                            ('notifications_enabled', Mock(return_value=True)), ('firmware_installing', Mock(return_value=False))):
            patcher = patch.object(tessera_tray, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = host_support.tray_app(Mock())
        self.app.icon, self.app.host, self.app.asked_autostart = Mock(), Mock(), True

    def host_stops(self, stop_pressed):
        """The tray sees the host run, then go down. Stop host in the terminal was pressed `stop_pressed` seconds
        after the tray saw the host start."""
        self.app.controller.status.return_value = {'running': True, 'device': {}}
        self.app.refresh()
        self.marker.write_text('{}', encoding='utf-8')
        moment = self.app.started_at + stop_pressed
        os.utime(self.marker, (moment, moment))
        self.app.controller.status.return_value = {'running': False}
        self.app.refresh()
        start = time.monotonic()
        for later in (10, 60, 400):
            self.app.watch_host(False, start + later)
            self.app.report_trouble(self.tray.trouble_text(self.app.status), start + later)

    def test_stop_host_in_the_terminal_keeps_the_host_stopped_without_a_crash_notice(self):
        self.host_stops(3)
        self.app.host.assert_not_called()
        self.app.icon.notify.assert_not_called()

    def test_a_stop_from_before_this_host_started_does_not_hold_back_its_restart(self):
        self.host_stops(-60)
        self.app.host.assert_called()
        self.assertIn('stopped unexpectedly', self.app.icon.notify.call_args_list[0].args[0])


if __name__ == '__main__':
    unittest.main()
