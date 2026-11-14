"""Home Assistant keys (stage C, "ha":1): homeassistant steps and followed entities, checked, sent, and never run twice."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import host_support  # noqa: E402
import action_preview  # noqa: E402
import config_check  # noqa: E402
import ha_keys  # noqa: E402
import import_review  # noqa: E402
import panel_serial  # noqa: E402

STEP = {'type': 'homeassistant', 'action': 'light.toggle', 'entity_id': 'light.kitchen', 'data': {'brightness_pct': 50}}
FOLLOW = {'entity_id': 'sensor.living_room_temperature', 'show': 'value', 'unit': '°C'}


def config_with(*buttons, triggers=None):
    config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
    profile = next(iter(config['profiles'].values()))
    name = next(iter(profile['pages']))
    profile['pages'][name] = list(buttons)
    profile.pop('pinned', None)
    if triggers is not None:
        config['triggers'] = triggers
    return config


def key(bid=1, **extra):
    return {'id': bid, 'label': 'Kitchen', 'icon': 'ok', 'color': '#35D07F', **extra}


class ConfigRules(unittest.TestCase):
    def assert_refused(self, config, words):
        with self.assertRaises(ValueError) as raised:
            config_check.validate_config(config)
        self.assertIn(words, str(raised.exception))

    def test_valid_steps_and_follow(self):
        config_check.validate_config(config_with(
            key(actions=[STEP, {'type': 'homeassistant', 'action': 'scene.turn_on', 'entity_id': 'scene.a, scene.b'}],
                hold_actions=[{'type': 'homeassistant', 'action': 'script.turn_on'}],
                double_actions=[dict(STEP, data={'on': True, 'level': 0.5, 'name': 'x'})], ha_state=FOLLOW),
            key(2, ha_state={'entity_id': 'light.kitchen', 'attribute': 'brightness', 'show': 'both', 'on': ['on', 'home']})))

    def test_bad_steps(self):
        cases = [({'action': 'Light.Toggle'}, 'domain.service'), ({'action': 'light'}, 'domain.service'),
                 ({'action': 'a.' + 'b' * 63}, 'domain.service'), ({'entity_id': 'kitchen'}, 'light.kitchen'),
                 ({'entity_id': ','.join(f'light.l{i}' for i in range(5))}, 'at most 4'),
                 ({'entity_id': ','.join('light.' + 'x' * 40 for _ in range(4))}, '128'),
                 ({'data': {f'k{i}': 1 for i in range(5)}}, 'at most 4'), ({'data': {'Bad': 1}}, 'data names'),
                 ({'data': {'entity_id': 'light.x'}}, 'data names'), ({'data': {'v': 'x' * 65}}, '64'),
                 ({'data': {'v': [1]}}, 'text, numbers'), ({'data': {'v': float('nan')}}, 'text, numbers'),
                 ({'data': 'x'}, 'object'), ({'service': 'x'}, 'unknown field'), ({'action': 5}, 'must be text')]
        for change, words in cases:
            with self.subTest(change=change):
                self.assert_refused(config_with(key(actions=[dict(STEP, **change)])), words)

    def test_limits_and_where_steps_may_go(self):
        self.assert_refused(config_with(key(actions=[STEP] * 3)), 'at most 2')
        self.assert_refused(config_with(*[key(i, actions=[STEP] * 2, hold_actions=[STEP] * 2) for i in range(1, 8)]), 'at most 24')
        self.assert_refused(config_with(key(states=[{'label': 'a', 'actions': [STEP]}, {'label': 'b'}])), 'run on the panel')
        self.assert_refused(config_with(key(), triggers=[{'when': {'type': 'interval', 'seconds': 5}, 'actions': [STEP]}]),
                            'run on the panel')

    def test_bad_follow(self):
        cases = [({'entity_id': 'a.b,c.d'}, 'one entity'), ({'entity_id': 'x'}, 'light.kitchen'), ({'attribute': 'A'}, 'attribute'),
                 ({'show': 'icon'}, 'show'), ({'on': []}, 'on must'), ({'on': ['x' * 17]}, 'on must'), ({'unit': 'x' * 7}, 'unit'),
                 ({'colour': 1}, 'needs entity_id')]
        for change, words in cases:
            with self.subTest(change=change):
                self.assert_refused(config_with(key(ha_state=dict(FOLLOW, **change))), words)


class Layout(unittest.TestCase):
    def test_fields_follow_the_design(self):
        button = key(actions=[{'type': 'hotkey', 'keys': 'ctrl+c'}, STEP], hold_actions=[{'type': 'homeassistant', 'action': 'scene.turn_on'}],
                     ha_state={'entity_id': 'light.kitchen'})
        self.assertEqual(ha_keys.layout_fields(button), {
            'ha': {'p': [{'a': 'light.toggle', 'e': 'light.kitchen', 'd': {'brightness_pct': '50'}}], 'h': [{'a': 'scene.turn_on'}]},
            'hs': {'e': 'light.kitchen', 'a': '', 'm': 'a', 'on': ['on'], 'u': ''}})
        self.assertEqual(ha_keys.step_entry(dict(STEP, entity_id='light.a , light.b', data={'t': True, 'f': False, 'x': 1.5})),
                         {'a': 'light.toggle', 'e': 'light.a,light.b', 'd': {'t': 'true', 'f': 'false', 'x': '1.5'}})
        self.assertEqual(ha_keys.layout_fields(key()), {})


class Daemon(host_support.HostCase):
    def setUp(self):
        button = key(actions=[STEP], double_actions=[{'type': 'hotkey', 'keys': 'ctrl+c'}, STEP], ha_state=FOLLOW)
        self.d = self.daemon(config_with(button, key(2, actions=[{'type': 'set', 'variable': 'x', 'value': '1'}])))
        self.d.profile = next(iter(self.d.config['profiles']))
        self.d.page = next(iter(self.d.config['profiles'][self.d.profile]['pages']))
        self.d.connection_failed.clear()
        self.d.panel.supports_api.return_value = True
        self.d.run_hotkey = Mock()

    def entry(self):
        return next(item for item in self.d.current_buttons() if item['id'] == 1)

    def test_layout_only_for_panels_with_ha(self):
        self.d.panel.supports_ha.return_value = False
        self.assertNotIn('ha', self.entry())
        self.assertNotIn('hs', self.entry())
        self.d.panel.supports_ha.return_value = True
        entry = self.entry()
        self.assertEqual(entry['ha'], {'p': [{'a': 'light.toggle', 'e': 'light.kitchen', 'd': {'brightness_pct': '50'}}],
                                       'd': [{'a': 'light.toggle', 'e': 'light.kitchen', 'd': {'brightness_pct': '50'}}]})
        self.assertEqual(entry['hs']['m'], 'v')
        self.assertTrue(entry['double'])
        self.assertLessEqual(panel_serial.layout_bytes(self.d.current_buttons()), panel_serial.OFFLINE_LAYOUT_BYTES)

    def test_host_never_runs_it_and_sends_no_feedback_for_panel_only_presses(self):
        self.d.panel.supports_ha.return_value = True
        self.d.panel.feedback = Mock()
        self.assertTrue(self.d.dispatch_press(1))
        self.d.panel.feedback.assert_not_called()  # the panel flashes it
        self.assertTrue(any('run by the panel' in str(call) for call in self.d.log.call_args_list))
        self.assertTrue(self.d.dispatch_press(2))
        self.d.panel.feedback.assert_called_once()

    def test_old_firmware_reports_a_failed_press(self):
        self.d.panel.supports_ha.return_value = False
        self.d.panel.feedback = Mock()
        self.assertFalse(self.d.dispatch_press(1))
        self.assertIn('update the panel firmware', self.d.last_action['error'])
        self.assertFalse(self.d.panel.feedback.call_args.args[1])

    def test_mixed_list_runs_only_the_pc_steps(self):
        self.d.panel.supports_ha.return_value = True
        self.d.panel.feedback = Mock()
        ran = []
        original = self.d.run_action
        self.d.run_action = lambda action: (ran.append(action['type']), original(action) if action['type'] == 'homeassistant' else None)
        self.assertTrue(self.d.dispatch_press(1, double=True))
        self.assertEqual(ran, ['hotkey', 'homeassistant'])
        self.d.panel.feedback.assert_called_once()  # the PC ran a step, so the PC gives the feedback


class Panel(unittest.TestCase):
    def test_supports_ha_needs_api_and_ha(self):
        panel = panel_serial.PanelSerial.__new__(panel_serial.PanelSerial)
        for info, wanted in (({'api': 1, 'ha': 1}, True), ({'api': 1}, False), ({'ha': 1}, False), ({'api': 1, 'ha': '1'}, False)):
            panel.info = info
            self.assertIs(panel.supports_ha(), wanted, info)


class ReviewAndPreview(unittest.TestCase):
    def test_import_review_says_it_reaches_the_network_and_safe_import_drops_it(self):
        config = config_with(key(actions=[STEP]))
        found = [item for item in import_review.review(config) if item['kind'] == 'homeassistant']
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['risk'], 'medium')
        self.assertIn('light.toggle', found[0]['detail'])
        safe = import_review.strip_executable(copy.deepcopy(config))
        self.assertEqual(next(iter(next(iter(safe['profiles'].values()))['pages'].values()))[0]['actions'], [])

    def test_preview(self):
        report = action_preview.preview([STEP], {})
        self.assertTrue(report['ok'])
        self.assertTrue(report['steps'][0]['text'].startswith('Home Assistant: light.toggle on light.kitchen'))



class HaSimulator(unittest.TestCase):
    def test_states_and_toggles(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import esphome_check
        states = esphome_check.parse_states(['input_boolean.t=off', 'light.k@brightness=128'])
        self.assertEqual(states, {('input_boolean.t', ''): 'off', ('light.k', 'brightness'): '128'})
        self.assertEqual(esphome_check.simulated_state('input_boolean.toggle', {'entity_id': 'input_boolean.t'}, states),
                         [('input_boolean.t', 'on')])
        self.assertEqual(esphome_check.simulated_state('light.toggle', {'entity_id': 'input_boolean.t'}, states), [])
        self.assertEqual(esphome_check.simulated_state('homeassistant.turn_off', {'entity_id': 'input_boolean.t'}, states),
                         [('input_boolean.t', 'off')])
        with self.assertRaises(ValueError):
            esphome_check.parse_states(['nodot=1'])


if __name__ == '__main__':
    unittest.main()
