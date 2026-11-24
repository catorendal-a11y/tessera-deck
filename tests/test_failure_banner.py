"""Why a key failed: plugin keys whose plugin cannot take the command, and the reason on the panel's banner."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import host_support  # noqa: E402
import plugins  # noqa: E402
from daemon_display import banner_text  # noqa: E402

OFF = 'OBS Studio is off: turn it on in More → Plugins'


def make_daemon(info=None):
    daemon = host_support.test_daemon()
    daemon.panel, daemon.log, daemon.publish_runtime, daemon.notify = Mock(), Mock(), Mock(), Mock()
    daemon.device_info = {'protocol': 4, 'notify': 1} if info is None else info
    daemon.stop.clear()
    daemon.profile, daemon.page = 'main', 'main'
    return daemon


def set_actions(daemon, actions, button_id=1):
    next(b for b in daemon.config['profiles']['main']['pages']['main'] if b['id'] == button_id)['actions'] = actions


def banners(daemon):
    return [c.args[0] for c in daemon.panel.send_line.call_args_list if c.args[0].startswith('AD_NOTIFY')]


class PluginKeyTests(unittest.TestCase):
    def daemon(self, enabled=True, state='running', plugin='obs'):
        daemon = make_daemon()
        daemon.plugins = plugins.PluginManager(ROOT / 'plugins', host_support.FOLDER / 'logs', Mock(), Mock(), Mock())
        daemon.plugins.manifests = {'obs': plugins.load_manifest(ROOT / 'plugins' / 'obs')}
        daemon.plugins.history['obs'] = dict(plugins._blank(), state=state)
        daemon.config['plugins'] = {'obs': {'enabled': enabled, 'settings': {}}}
        set_actions(daemon, [{'type': 'plugin', 'plugin': plugin, 'command': 'record'}])
        return daemon

    def commands(self, daemon):
        return [event for event in daemon.events.since(0, 'obs') if event['type'] == 'command']

    def assert_refused(self, daemon, reason):
        self.assertFalse(daemon.dispatch_press(1))
        self.assertEqual(daemon.last_action['error'], reason)
        daemon.panel.feedback.assert_called_once_with(1, False)
        self.assertEqual(self.commands(daemon), [])

    def test_a_plugin_that_is_off_turns_the_press_red_and_says_where_to_turn_it_on(self):
        self.assert_refused(self.daemon(enabled=False), OFF)

    def test_a_crashed_or_failed_plugin_turns_the_press_red(self):
        self.assert_refused(self.daemon(state='crashed'), 'OBS Studio has stopped')
        self.assert_refused(self.daemon(state='failed'), 'Plugin stopped: turn it off and on in More → Plugins (OBS Studio)')

    def test_a_plugin_held_back_by_the_keyring_says_to_unlock_it_or_type_the_secret_again(self):
        import action_preview
        import platform_linux.secrets as keyring_secrets
        import secrets_store
        # a locked keyring, and an open one without this id (the profile came from another PC): unlocking fixes only the first
        for answer in ({'side_effect': OSError('locked')}, {'return_value': None}):
            with self.subTest(answer=answer):
                daemon = self.daemon(state='stopped')
                daemon.plugins._spawn, daemon.plugins._log = Mock(), Mock()
                daemon.config['plugins']['obs']['settings'] = {'password': '$(keyring:abc)'}
                with patch.object(secrets_store, 'load', return_value=keyring_secrets), \
                        patch.object(keyring_secrets, 'fetch', **answer):
                    daemon.plugins.sync(daemon.config['plugins'])
                daemon.plugins._spawn.assert_not_called()
                status = next(item for item in daemon.plugins.status(daemon.config['plugins']) if item['id'] == 'obs')
                self.assertEqual(status['state'], 'waiting')  # what the plugin list in the editor shows
                self.assertIn('unlock it', status['error'].lower())
                said = 'Unlock the keyring or type the secret again in the editor (OBS Studio)'
                self.assertEqual(action_preview.preview([{'type': 'plugin', 'plugin': 'obs', 'command': 'record'}], {},
                                                        plugins=[status])['steps'][0]['text'], said)
                self.assert_refused(daemon, said)
                self.assertEqual(banners(daemon), ['AD_NOTIFY error 6 ' + said], 'the panel cut the reason short')

    def test_a_plugin_with_the_longest_name_a_manifest_allows_still_shows_the_whole_advice(self):
        import dataclasses
        import action_preview
        name = 'A' * 60  # load_manifest takes names of 1-60 characters
        # as the panel shows it (its font has no →), up to the bracket before the name
        for state, advice in (('waiting', 'type the secret again in the editor ('), ('failed', 'turn it off and on in More > Plugins (')):
            with self.subTest(state=state):
                daemon = self.daemon(state=state)
                daemon.plugins.manifests['obs'] = dataclasses.replace(daemon.plugins.manifests['obs'], name=name)
                self.assertFalse(daemon.dispatch_press(1))
                [banner] = banners(daemon)
                self.assertIn(advice, banner, 'the panel cut the advice short')
                self.assertEqual(action_preview.preview([{'type': 'plugin', 'plugin': 'obs', 'command': 'record'}], {}, plugins=[
                    {'id': 'obs', 'name': name, 'enabled': True, 'state': state}])['steps'][0]['text'], daemon.last_action['error'])

    def test_a_plugin_that_is_not_installed_turns_the_press_red(self):
        daemon = self.daemon(plugin='ghost')
        self.assertFalse(daemon.dispatch_press(1))
        self.assertEqual(daemon.last_action['error'], 'The ghost plugin is not installed')

    def test_a_running_plugin_gets_the_command_with_the_key_that_sent_it(self):
        daemon = self.daemon()
        self.assertTrue(daemon.dispatch_press(1))
        daemon.panel.feedback.assert_called_once_with(1, True)
        self.assertEqual([(e['command'], e['button']) for e in self.commands(daemon)], [('record', 1)])
        self.assertEqual(banners(daemon), [])

    def test_a_trigger_sends_the_command_without_a_key(self):
        daemon = self.daemon()
        daemon.run_action({'type': 'plugin', 'plugin': 'obs', 'command': 'record'})
        self.assertNotIn('button', self.commands(daemon)[0])


class FailureBannerTests(unittest.TestCase):
    def fail_with(self, daemon, message):
        set_actions(daemon, [{'type': 'set', 'variable': 'x', 'value': '1'}])
        with patch.object(daemon, 'run_action', side_effect=RuntimeError(message)):
            self.assertFalse(daemon.dispatch_press(1))

    def test_a_failed_press_shows_the_same_reason_as_the_editor_on_one_line(self):
        daemon = make_daemon()
        self.fail_with(daemon, 'line one\nline\ttwo \x1b[0m\x00end')
        self.assertEqual(banners(daemon), ['AD_NOTIFY error 6 line one line two [0mend'])
        self.assertEqual(banners(daemon)[0], 'AD_NOTIFY error 6 ' + banner_text(daemon.last_action['error']))
        daemon.notify.assert_not_called()

    def test_a_long_reason_is_cut_to_what_the_panel_takes(self):
        daemon = make_daemon()
        self.fail_with(daemon, 'x' * 300)
        text = banners(daemon)[0].removeprefix('AD_NOTIFY error 6 ')
        self.assertEqual(text, 'x' * 99 + '…')

    def test_no_banner_without_a_panel_that_has_one_and_no_windows_notification(self):
        for panel, info in ((None, {'notify': 1}), (Mock(), {'protocol': 4}), (Mock(), {'notify': True})):
            with self.subTest(info=info, panel=panel):
                daemon = make_daemon(info)
                daemon.panel = panel
                self.fail_with(daemon, 'boom')
                if panel is not None:
                    self.assertEqual(banners(daemon), [])
                daemon.notify.assert_not_called()

    def test_a_panel_that_drops_the_line_does_not_turn_into_a_windows_notification(self):
        daemon = make_daemon()
        daemon.panel.send_line.side_effect = OSError('gone')
        self.fail_with(daemon, 'boom')
        daemon.notify.assert_not_called()
        daemon.publish_runtime.assert_called()

    def test_stopping_and_an_unknown_key_show_nothing(self):
        daemon = make_daemon()
        daemon.stop.set()
        set_actions(daemon, [{'type': 'set', 'variable': 'x', 'value': '1'}])
        self.assertFalse(daemon.dispatch_press(1))
        self.assertEqual(daemon.last_action['error'], 'Stopping')
        unknown = make_daemon()
        self.assertFalse(unknown.dispatch_press(99))  # a tap that crossed a page change
        self.assertEqual(banners(daemon) + banners(unknown), [])

    def test_a_failing_child_key_shows_its_own_reason_once(self):
        daemon = make_daemon()
        set_actions(daemon, [{'type': 'press', 'id': 2}], 1)
        set_actions(daemon, [{'type': 'screen', 'show': 'clock'}], 2)
        daemon.device_info = {'protocol': 2, 'notify': 1}
        self.assertFalse(daemon.dispatch_press(1))
        reason = 'The panel firmware does not have the clock screen; update it first'
        self.assertEqual(daemon.last_action['error'], reason)
        self.assertEqual(banners(daemon), [f'AD_NOTIFY error 6 {reason}'])


class BannerTextTests(unittest.TestCase):
    def test_the_text_always_fits_the_firmware(self):
        for text in ('a  b\r\n\tc', '​\ud800x', '😀' * 150, 'é' * 100, 'y' * 101, ' \n '):
            line = banner_text(text)
            self.assertLessEqual(len(line), 100)
            self.assertLessEqual(len(line.encode('utf-8')), 400)
            self.assertTrue(line.isprintable(), repr(line))
            self.assertEqual(line, line.strip())
        self.assertEqual(banner_text('a  b\r\n\tc'), 'a b c')
        self.assertEqual(banner_text('é' * 100), 'é' * 100)
        self.assertEqual(banner_text('y' * 101), 'y' * 99 + '…')
        self.assertEqual(banner_text(' \n '), '')

    def test_a_menu_path_uses_a_character_the_panel_font_has(self):
        self.assertEqual(banner_text('OBS Studio is off: turn it on in More → Plugins'),
                         'OBS Studio is off: turn it on in More > Plugins')


if __name__ == '__main__':
    unittest.main()
