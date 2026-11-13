"""Panel features the host drives: hold-to-confirm keys ("cf":1), the panel lock and the panel's brightness slider."""
import copy
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck  # noqa: E402
import host_support  # noqa: E402
from action_preview import preview  # noqa: E402


class ConfirmKeyTests(unittest.TestCase):
    def setUp(self):
        self.daemon = host_support.test_daemon()
        self.daemon.profile, self.daemon.page = 'main', 'main'
        self.button = next(b for b in self.daemon.config['profiles']['main']['pages']['main'] if b['id'] == 1)

    def test_a_confirm_key_reaches_the_panel_as_cf(self):
        self.button['confirm'] = True
        shown = {b['id']: b for b in self.daemon.current_buttons()}
        self.assertEqual(shown[1]['cf'], 1)
        self.assertNotIn('cf', shown[2])

    def test_confirm_is_checked(self):
        config = copy.deepcopy(self.daemon.config)
        key = next(b for b in config['profiles']['main']['pages']['main'] if b['id'] == 1)
        key['confirm'] = True
        deck.validate_config(config)
        key['confirm'] = 'yes'
        with self.assertRaisesRegex(ValueError, 'confirm'):
            deck.validate_config(config)
        key['confirm'], key['hold_actions'] = True, [{'type': 'delay', 'ms': 1}]
        with self.assertRaisesRegex(ValueError, 'confirm'):
            deck.validate_config(config)


class PanelLockTests(unittest.TestCase):
    def setUp(self):
        self.daemon = host_support.test_daemon()
        self.daemon.panel, self.daemon.log = Mock(), Mock()

    def sent(self):
        return [call.args[0] for call in self.daemon.panel.send_line.call_args_list]

    def test_the_action_toggles_or_sets_the_lock(self):
        self.daemon.run_action({'type': 'panel_lock'})
        self.daemon.run_action({'type': 'panel_lock', 'mode': 'on'})
        self.daemon.run_action({'type': 'panel_lock', 'mode': 'toggle'})
        self.daemon.run_action({'type': 'panel_lock', 'mode': 'off'})
        self.assertEqual(self.sent(), ['AD_PANEL_LOCK 1', 'AD_PANEL_LOCK 1', 'AD_PANEL_LOCK 0', 'AD_PANEL_LOCK 0'])
        self.assertFalse(self.daemon.panel_locked)

    def test_unlocking_on_the_panel_updates_the_host(self):
        self.daemon.run_action({'type': 'panel_lock', 'mode': 'on'})
        self.daemon.handle_job(('panel-unlocked',))
        self.assertFalse(self.daemon.panel_locked)
        self.daemon.run_action({'type': 'panel_lock'})
        self.assertEqual(self.sent()[-1], 'AD_PANEL_LOCK 1')

    def test_the_mode_is_checked_and_previewed(self):
        config = copy.deepcopy(self.daemon.config)
        key = next(b for b in config['profiles']['main']['pages']['main'] if b['id'] == 1)
        key['actions'] = [{'type': 'panel_lock', 'mode': 'on'}]
        deck.validate_config(config)
        key['actions'] = [{'type': 'panel_lock', 'mode': 'sometimes'}]
        with self.assertRaisesRegex(ValueError, 'panel_lock'):
            deck.validate_config(config)
        self.assertEqual(preview([{'type': 'panel_lock', 'mode': 'on'}], {})['steps'][0]['text'], 'Lock the panel')


class PanelBrightnessTests(unittest.TestCase):
    def setUp(self):
        self.path = host_support.FOLDER / 'brightness.json'
        shutil.copyfile(host_support.PROFILES, self.path)
        self.daemon = host_support.test_daemon(self.path)
        self.daemon.panel, self.daemon.log = Mock(), Mock()

    def display(self):
        return json.loads(self.path.read_text(encoding='utf-8')).get('display', {})

    def test_the_slider_level_is_kept_as_the_brightness(self):
        self.daemon.handle_job(('panel-brightness', 40))
        self.assertEqual(self.display()['brightness'], 40)
        self.assertEqual(self.daemon.sent_brightness, 40)

    def test_in_quiet_hours_it_sets_the_night_level(self):
        night = {'from': '00:00', 'to': '23:59', 'brightness': 10}
        config = json.loads(self.path.read_text(encoding='utf-8'))
        config['display'] = dict(config.get('display', {}), night=night)
        self.path.write_text(json.dumps(config), encoding='utf-8')
        with patch.object(self.daemon, 'minute_of_day', return_value=600):
            self.daemon.handle_job(('panel-brightness', 25))
        self.assertEqual(self.display()['night']['brightness'], 25)
        self.assertNotEqual(self.display().get('brightness'), 25)


if __name__ == '__main__':
    unittest.main()
