"""The screen action (clock or keys on demand) and quiet hours (a lower brightness at night)."""
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck
from action_preview import preview


def make_daemon(protocol=3):
    daemon = deck.Daemon(types.SimpleNamespace(profiles=str(ROOT / 'host/profiles.default.json'), port='TEST',
                                               verbose=False, no_focus=True, deck_only=True))
    daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
    daemon.device_info = {'protocol': protocol}
    return daemon


def sent(daemon):
    return [call.args[0] for call in daemon.panel.send_line.call_args_list]


class ScreenActionTests(unittest.TestCase):
    def test_the_action_is_validated(self):
        config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        button = config['profiles']['main']['pages']['main'][0]
        for show in ('clock', 'keys', 'toggle'):
            button['actions'] = [{'type': 'screen', 'show': show}]
            deck.validate_config(config)
        for bad in ({'type': 'screen'}, {'type': 'screen', 'show': 'banana'}, {'type': 'screen', 'show': 5}):
            button['actions'] = [bad]
            with self.subTest(bad), self.assertRaises(ValueError):
                deck.validate_config(config)

    def test_clock_shows_the_clock_even_when_the_idle_clock_is_off(self):
        daemon = make_daemon()
        daemon.run_action({'type': 'screen', 'show': 'clock'})
        self.assertIn('AD_SCREEN ambient', sent(daemon))
        self.assertTrue(daemon.ambient_active)
        daemon.panel.send_line.reset_mock()
        daemon.ambient_tick(10_000.0)  # the idle clock is disabled, but this one was asked for
        self.assertNotIn('AD_SCREEN deck', sent(daemon))
        self.assertTrue(daemon.ambient_active)

    def test_keys_brings_the_keys_back_and_clears_the_request(self):
        daemon = make_daemon()
        daemon.run_action({'type': 'screen', 'show': 'clock'})
        daemon.run_action({'type': 'screen', 'show': 'keys'})
        self.assertEqual(sent(daemon)[-1], 'AD_SCREEN deck')
        self.assertFalse(daemon.ambient_active)
        daemon.ambient_tick(10_000.0)
        self.assertFalse(daemon.ambient_active)

    def test_toggle_switches_between_the_two(self):
        daemon = make_daemon()
        daemon.run_action({'type': 'screen', 'show': 'toggle'})
        self.assertTrue(daemon.ambient_active)
        daemon.run_action({'type': 'screen', 'show': 'toggle'})
        self.assertFalse(daemon.ambient_active)

    def test_a_touch_on_the_clock_ends_the_request(self):
        daemon = make_daemon()
        daemon.run_action({'type': 'screen', 'show': 'clock'})
        daemon.handle_job(('screen-deck',))
        self.assertFalse(daemon.ambient_active)
        daemon.ambient_tick(10_000.0)
        self.assertFalse(daemon.ambient_active)

    def test_old_firmware_gets_a_clear_answer(self):
        daemon = make_daemon(protocol=2)
        with self.assertRaisesRegex(ValueError, 'firmware'):
            daemon.run_action({'type': 'screen', 'show': 'clock'})
        self.assertFalse(daemon.ambient_active)

    def test_the_dry_run_explains_it(self):
        result = preview([{'type': 'screen', 'show': 'clock'}, {'type': 'screen', 'show': 'toggle'}], {})
        self.assertTrue(result['ok'])
        self.assertIn('clock', result['steps'][0]['text'].lower())
        self.assertIn('switch', result['steps'][1]['text'].lower())


NIGHT = {'from': '23:00', 'to': '07:00', 'brightness': 5}


def at(hour, minute=0):
    return deck.in_quiet_hours(NIGHT, hour * 60 + minute)


class QuietHoursTests(unittest.TestCase):
    def test_the_window_wraps_past_midnight(self):
        self.assertTrue(at(23) and at(0) and at(6, 59))
        self.assertFalse(at(7) or at(12) or at(22, 59))

    def test_a_window_within_one_day_and_an_empty_window(self):
        day = {'from': '09:00', 'to': '17:00', 'brightness': 30}
        self.assertTrue(deck.in_quiet_hours(day, 12 * 60))
        self.assertFalse(deck.in_quiet_hours(day, 20 * 60))
        self.assertFalse(deck.in_quiet_hours({'from': '08:00', 'to': '08:00', 'brightness': 5}, 8 * 60))
        self.assertFalse(deck.in_quiet_hours(None, 0))

    def test_the_settings_are_validated(self):
        deck._check_display({'night': NIGHT})
        for bad in ({'from': '25:00', 'to': '07:00', 'brightness': 5}, {'from': '23:00', 'to': '07:00'},
                    {'from': '23:00', 'to': '07:00', 'brightness': 0},
                    {'from': '23:00', 'to': '07:00', 'brightness': 5, 'x': 1},
                    'night', {'from': 2300, 'to': '07:00', 'brightness': 5}):
            with self.subTest(bad), self.assertRaises(ValueError):
                deck._check_display({'night': bad})

    def test_brightness_follows_the_clock(self):
        daemon = make_daemon()
        daemon.config['display'] = {'brightness': 80, 'night': NIGHT}
        daemon.minute_of_day = lambda: 23 * 60 + 30
        daemon.apply_brightness()
        self.assertEqual(sent(daemon)[-1], 'AD_BRIGHTNESS 5')
        daemon.minute_of_day = lambda: 12 * 60
        daemon.apply_brightness()
        self.assertEqual(sent(daemon)[-1], 'AD_BRIGHTNESS 80')

    def test_the_tick_changes_brightness_only_when_the_wanted_value_changes(self):
        daemon = make_daemon()
        daemon.config['display'] = {'brightness': 80, 'night': NIGHT}
        daemon.minute_of_day = lambda: 12 * 60
        daemon.apply_brightness()
        daemon.brightness_tick()
        self.assertTrue(daemon.jobs.empty())
        daemon.minute_of_day = lambda: 23 * 60 + 1
        daemon.brightness_tick()
        self.assertEqual(daemon.jobs.get_nowait(), ('brightness',))

    def test_a_dimmed_panel_is_left_alone_until_it_wakes(self):
        daemon = make_daemon()
        daemon.config['display'] = {'brightness': 80, 'night': NIGHT}
        daemon.minute_of_day = lambda: 12 * 60
        daemon.apply_brightness()
        daemon.dimmed = True
        daemon.minute_of_day = lambda: 23 * 60 + 1
        daemon.brightness_tick()
        self.assertTrue(daemon.jobs.empty())

    def test_without_quiet_hours_nothing_changes(self):
        daemon = make_daemon()
        daemon.config['display'] = {'brightness': 60}
        daemon.apply_brightness()
        daemon.brightness_tick()
        self.assertEqual(sent(daemon)[-1], 'AD_BRIGHTNESS 60')
        self.assertTrue(daemon.jobs.empty())


if __name__ == '__main__':
    unittest.main()
