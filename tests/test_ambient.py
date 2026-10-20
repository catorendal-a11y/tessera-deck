"""Ambient clock and weather line, per-key colors; no network and no hardware."""
import json
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import ambient
import tesserad as deck


class FakeReply:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, limit):
        return self.payload[:limit]


def opener_for(payload, calls=None):
    def opener(request, timeout):
        if calls is not None:
            calls.append(request.full_url)
        return FakeReply(payload)
    return opener


class SettingsTests(unittest.TestCase):
    def test_valid_and_invalid_ambient_blocks(self):
        ambient.check_ambient({'enabled': True, 'after': 60,
                               'weather': {'name': 'Oslo', 'latitude': 59.9, 'longitude': 10.7, 'unit': 'celsius'}})
        ambient.check_ambient({'enabled': False})
        for bad in ({'enabled': 'yes'}, {'enabled': True, 'after': 5}, {'enabled': True, 'after': '60'},
                    {'enabled': True, 'weather': {'latitude': 99, 'longitude': 0}},
                    {'enabled': True, 'weather': {'latitude': 1, 'longitude': 1, 'unit': 'kelvin'}},
                    {'enabled': True, 'weather': {'latitude': True, 'longitude': 1}}, [], None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ambient.check_ambient(bad)

    def test_the_config_validator_checks_ambient_and_key_colors(self):
        config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        config['ambient'] = {'enabled': True, 'after': 90}
        deck.validate_config(config)
        config['ambient'] = {'enabled': True, 'after': 1}
        with self.assertRaises(ValueError):
            deck.validate_config(config)
        del config['ambient']
        button = config['profiles']['main']['pages']['main'][0]
        button.update(bg='#102030', text_color='#FFAA00', border='#00FF00')
        deck.validate_config(config)
        button['border'] = 'green'
        with self.assertRaises(ValueError):
            deck.validate_config(config)


class WeatherTests(unittest.TestCase):
    def test_description_in_celsius_and_fahrenheit(self):
        current = {'temperature_2m': 11.6, 'weather_code': 2}
        self.assertEqual(ambient.describe(current, 'Oslo', 'celsius'), '12 C, Partly cloudy - Oslo')
        self.assertEqual(ambient.describe({'temperature_2m': 50, 'weather_code': 999}, '', 'fahrenheit'), '50 F')
        with self.assertRaises(ValueError):
            ambient.describe({}, 'Oslo', 'celsius')

    def test_the_forecast_request_carries_only_coordinates_and_units(self):
        url = ambient.forecast_url(59.9139, 10.7522, 'celsius')
        self.assertTrue(url.startswith('https://api.open-meteo.com/v1/forecast?'))
        for part in ('latitude=59.9139', 'longitude=10.7522', 'temperature_unit=celsius'):
            self.assertIn(part, url)

    def test_search_returns_places_and_rejects_short_queries(self):
        reply = {'results': [{'name': 'Oslo', 'admin1': 'Oslo', 'country': 'Norway', 'latitude': 59.9,
                              'longitude': 10.7}, {'name': 'Broken'}]}
        places = ambient.search_places('Oslo', opener_for(reply))
        self.assertEqual(places, [{'name': 'Oslo', 'region': 'Oslo', 'country': 'Norway', 'latitude': 59.9,
                                   'longitude': 10.7}])
        self.assertEqual(ambient.search_places('Nowhere', opener_for({})), [])
        with self.assertRaises(ValueError):
            ambient.search_places('O')

    def test_the_weather_line_refreshes_in_the_background_and_is_cached(self):
        calls = []
        weather = ambient.Weather(opener_for({'current': {'temperature_2m': 3.2, 'weather_code': 71}}, calls))
        settings = {'enabled': True, 'weather': {'name': 'Tromso', 'latitude': 69.6, 'longitude': 18.9}}
        self.assertEqual(weather.line(settings), '')
        for _ in range(100):
            if weather.line(settings):
                break
            time.sleep(0.02)
        self.assertEqual(weather.line(settings), '3 C, Light snow - Tromso')
        weather.line(settings)
        self.assertEqual(len(calls), 1, 'a fresh answer is reused instead of asking again')

    def test_disabled_or_unset_weather_never_touches_the_network(self):
        calls = []
        weather = ambient.Weather(opener_for({}, calls))
        self.assertEqual(weather.line({'enabled': False, 'weather': {'latitude': 1, 'longitude': 1}}), '')
        self.assertEqual(weather.line({'enabled': True}), '')
        self.assertEqual(weather.line(None), '')
        time.sleep(0.05)
        self.assertEqual(calls, [])

    def test_a_failing_service_keeps_the_last_line_and_backs_off(self):
        clock = [0.0]
        answers = [{'current': {'temperature_2m': 5, 'weather_code': 0}}]

        def opener(request, timeout):
            if not answers:
                raise OSError('offline')
            return FakeReply(answers.pop())

        weather = ambient.Weather(opener, clock=lambda: clock[0])
        settings = {'enabled': True, 'weather': {'name': 'X', 'latitude': 1, 'longitude': 1}}
        weather.line(settings)
        for _ in range(100):
            if weather.line(settings):
                break
            time.sleep(0.02)
        clock[0] += ambient.REFRESH_SECONDS + 1
        weather.line(settings)
        time.sleep(0.2)
        self.assertEqual(weather.line(settings), '5 C, Clear sky - X')


class DaemonAmbientTests(unittest.TestCase):
    def daemon(self, protocol=3, **ambient_settings):
        daemon = deck.Daemon(types.SimpleNamespace(profiles=str(ROOT / 'host/profiles.default.json'), port='TEST',
                                                   verbose=False, no_focus=True, deck_only=True))
        daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
        daemon.device_info = {'protocol': protocol}
        daemon.config['ambient'] = dict({'enabled': True, 'after': 60}, **ambient_settings)
        daemon.weather = Mock(line=Mock(return_value='12 C, Clear sky - Oslo'))
        return daemon

    def test_the_ambient_screen_appears_after_the_idle_time_and_gets_its_line(self):
        daemon = self.daemon()
        daemon.last_activity = 1000.0
        daemon.ambient_tick(1030.0)
        daemon.panel.send_line.assert_not_called()
        daemon.ambient_tick(1061.0)
        self.assertEqual([call.args[0] for call in daemon.panel.send_line.call_args_list],
                         ['AD_SCREEN ambient', 'AD_AMBIENT 12 C, Clear sky - Oslo'])
        daemon.panel.send_line.reset_mock()
        daemon.ambient_tick(1062.0)
        daemon.panel.send_line.assert_not_called()  # the same line is not repeated

    def test_activity_returns_to_the_deck_and_a_touch_on_the_panel_needs_no_command(self):
        daemon = self.daemon()
        daemon.last_activity = 0.0
        daemon.ambient_tick(100.0)
        daemon.panel.send_line.reset_mock()
        daemon.wake_display()
        daemon.panel.send_line.assert_any_call('AD_SCREEN deck')
        self.assertFalse(daemon.ambient_active)
        daemon.last_activity = 0.0
        daemon.ambient_tick(100.0)
        daemon.panel.send_line.reset_mock()
        daemon.handle_job(('screen-deck',))
        self.assertFalse(daemon.ambient_active)
        daemon.panel.send_line.assert_not_called()

    def test_old_firmware_disabled_or_locked_states_never_show_the_screen(self):
        for daemon in (self.daemon(protocol=2), self.daemon(enabled=False)):
            daemon.last_activity = 0.0
            daemon.ambient_tick(1000.0)
            daemon.panel.send_line.assert_not_called()
        locked = self.daemon()
        locked.locked, locked.last_activity = True, 0.0
        locked.ambient_tick(1000.0)
        locked.panel.send_line.assert_not_called()

    def test_turning_the_feature_off_while_showing_leaves_the_screen(self):
        daemon = self.daemon()
        daemon.last_activity = 0.0
        daemon.ambient_tick(100.0)
        daemon.config['ambient']['enabled'] = False
        daemon.panel.send_line.reset_mock()
        daemon.ambient_tick(101.0)
        daemon.panel.send_line.assert_called_once_with('AD_SCREEN deck')

    def test_key_colors_are_sent_to_the_panel(self):
        daemon = self.daemon()
        daemon.profile, daemon.page = 'main', 'main'
        button = next(b for b in daemon.config['profiles']['main']['pages']['main'] if b['id'] == 1)
        button.update(bg='#102030', text_color='#FFAA00', border='#00FF00')
        entry = next(item for item in daemon.current_buttons() if item['id'] == 1)
        self.assertEqual((entry['bg'], entry['text_color'], entry['border']), ('#102030', '#FFAA00', '#00FF00'))
        plain = next(item for item in daemon.current_buttons() if item['id'] == 2)
        self.assertNotIn('bg', plain)


if __name__ == '__main__':
    unittest.main()
