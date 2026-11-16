"""A profile file saved by the Wi-Fi beta: this version loads it, keeps its Wi-Fi and Home Assistant parts and skips
the Home Assistant steps."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import config_store
import host_support
import import_review
import tesserad as deck
from action_preview import preview
from tessera_app import Editor
from test_editor import run_editor

HA = {'type': 'homeassistant', 'action': 'light.toggle', 'entity_id': 'light.kitchen', 'data': {'brightness': 80}}


def beta_config():
    """Every field the beta writes that this version does not use: panel.wifi, panel.homeassistant, Home Assistant
    steps in a key's press, hold and double lists, and ha_state."""
    return json.loads(json.dumps({'version': 2, 'default_profile': 'Main',
        'panel': {'wifi': {'ssid': 'Home'},
                  'homeassistant': {'enabled': True, 'name': 'tessera-deck', 'friendly_name': 'Tessera Deck', 'area': 'Office'}},
        'profiles': {'Main': {'match': [], 'pages': {'First': [
            {'id': 1, 'label': 'Lamp', 'icon': 'ok',
             'actions': [{'type': 'set', 'variable': 'before', 'value': '1'}, HA,
                         {'type': 'set', 'variable': 'after', 'value': '2'}],
             'hold_actions': [{'type': 'homeassistant', 'action': 'scene.turn_on', 'entity_id': 'scene.evening'}],
             'double_actions': [{'type': 'homeassistant', 'action': 'alarm_control_panel.alarm_disarm',
                                 'entity_id': 'alarm_control_panel.home', 'data': {'code': '1234'}}],
             'ha_state': {'entity_id': 'light.kitchen', 'show': 'both', 'on': ['on'], 'unit': ''}},
            {'id': 2, 'label': 'Copy', 'icon': 'ok', 'actions': [{'type': 'hotkey', 'keys': 'ctrl+c'}]}]}}}}))


def lamp(config):
    return config['profiles']['Main']['pages']['First'][0]


class BetaFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'profiles.json'
        self.path.write_text(json.dumps(beta_config()), encoding='utf-8')

    def test_a_beta_file_validates_and_home_assistant_steps_stay_on_keys(self):
        deck.validate_config(beta_config())
        on_keys, objects = "Home Assistant steps can only be in a key's", 'must be objects'
        refused = {'trigger': (on_keys, lambda c: c.setdefault('triggers', []).append({'when': {'type': 'startup'}, 'actions': [HA]})),
                   'shortcut': (on_keys, lambda c: c['panel'].setdefault('shortcuts', []).append({'type': 'actions', 'actions': [HA]})),
                   'state': (on_keys, lambda c: lamp(c).update(states=[{'label': 'a', 'actions': [HA]}, {'label': 'b'}])),
                   'timer': (on_keys, lambda c: lamp(c)['actions'].append({'type': 'timer', 'name': 't', 'actions': [HA]})),
                   'wifi': (objects, lambda c: c['panel'].update(wifi='Home')),
                   'homeassistant': (objects, lambda c: c['panel'].update(homeassistant=[]))}
        for where, (message, change) in refused.items():  # the beta refuses these too
            config = beta_config()
            change(config)
            with self.assertRaisesRegex(ValueError, message, msg=where):
                deck.validate_config(config)

    def test_the_host_does_not_swap_in_a_backup_at_start(self):
        older = beta_config()
        del older['panel']
        older['profiles']['Main']['pages']['First'].pop(0)
        self.path.write_text(json.dumps(older), encoding='utf-8')
        self.assertIsNotNone(config_store.backup(self.path, force=True))
        current = json.dumps(beta_config()).encode('utf-8')
        self.path.write_bytes(current)
        self.assertIsNone(config_store.recover(self.path))
        self.assertEqual(self.path.read_bytes(), current)
        self.assertFalse(self.path.with_name('profiles-unreadable.local.json').exists())

    def test_a_press_skips_the_home_assistant_step_and_runs_the_others(self):
        daemon = host_support.test_daemon(self.path)
        daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
        self.assertTrue(daemon.dispatch_press(1))
        self.assertEqual((daemon.custom_vars.get('before'), daemon.custom_vars.get('after')), ('1', '2'))
        self.assertTrue(daemon.dispatch_press(1))
        self.assertTrue(daemon.dispatch_press(1, hold=True))
        skipped = [call.args[0] for call in daemon.log.call_args_list if 'Home Assistant' in call.args[0]]
        self.assertEqual(skipped, ['Skipped a Home Assistant step on button 1: these run only on the beta panel firmware with Wi-Fi'],
                         'said once for the key, not on every press')
        self.assertFalse({'ha', 'hs', 'ha_state'} & set(daemon.current_buttons()[0]), 'the panel gets none of it')

    def test_the_dry_run_calls_the_step_beta_only_and_not_broken(self):
        report = preview(lamp(beta_config())['actions'], {})
        self.assertTrue(report['ok'])
        self.assertEqual(report['steps'][1]['text'], 'Skip Home Assistant light.toggle: it runs only on the beta firmware with Wi-Fi')

    def test_saves_from_the_editor_and_the_tray_keep_the_beta_fields(self):
        from tessera_tray import set_brightness
        editor = Editor(self.path, dashboard=lambda: {'running': False, 'device': {}})
        state = editor.read()
        changed = json.loads(json.dumps(state['config']))
        lamp(changed)['label'] = 'Lamp 2'
        editor.save({'config': changed, 'revision': state['revision']})
        set_brightness(40, self.path)
        saved, expected = json.loads(self.path.read_text(encoding='utf-8')), beta_config()
        lamp(expected)['label'] = 'Lamp 2'
        self.assertEqual(saved['panel'], expected['panel'])
        self.assertEqual(saved['profiles'], expected['profiles'])
        self.assertEqual(saved['display'], {'brightness': 40})

    def test_export_leaves_out_a_home_assistant_code_and_import_lists_the_steps(self):
        config = beta_config()
        shared, _ = import_review.redact_secrets(config)
        self.assertEqual(lamp(shared)['double_actions'][0]['data'], {}, 'an alarm code stays on this PC')
        self.assertEqual(lamp(shared)['actions'], lamp(config)['actions'])
        self.assertEqual(shared['panel'], config['panel'])
        self.assertEqual(import_review.export_left_out(config), ['Home Assistant data code'])
        deck.validate_config(shared)
        self.assertEqual([f['kind'] for f in import_review.review(config)], ['homeassistant'] * 3, 'the beta panel runs them')
        safe = import_review.strip_executable(config)
        self.assertEqual([[a['type'] for a in lamp(safe)[key]] for key in ('actions', 'hold_actions', 'double_actions')],
                         [['set', 'set'], [], []])
        deck.validate_config(safe)


class EditorScriptTests(unittest.TestCase):
    def test_the_editor_shows_a_beta_step_by_name_and_saves_it_as_it_is(self):
        found = run_editor(self, 'const BETA = ' + json.dumps(beta_config()) + ';\n' + r'''
config = clone(BETA); profile = 'Main'; page = 'First'; selected = 1; editState = 0;
const strings = [], realElement = element;
element = (tag, attrs = {}, ...children) => {
  strings.push(attrs.text, ...children.flat());
  return realElement(tag, attrs, ...children);
};
const key = config.profiles.Main.pages.First[0];
renderStep(key.actions[1], 1, 3);
element = realElement;
const result = {shown: strings.filter(item => typeof item === 'string' && item.includes('Home Assistant')),
  summary: stepSummary(key.actions), saved: JSON.stringify(savable(config)) === JSON.stringify(BETA)};
const offered = [];  // the keys a rule or a rail shortcut can copy its steps from
element = (tag, attrs = {}, ...children) => {
  if (tag === 'option') offered.push(...children.flat().filter(item => String(item).includes(' › First › ')));
  return realElement(tag, attrs, ...children);
};
autoDraft = [{when: {type: 'startup'}, actions: []}];
drawAuto();
railDraft = {order: ['keys'], on: new Set(['keys']), shortcuts: [{type: 'actions', actions: [], label: 'Steps', icon: 'lc:e0ff'}]};
drawRail();
element = realElement;
result.offered = offered;
const handlers = {}, realField = field;
field = (label, value, handler, options) => { handlers[label] = handler; return realField(label, value, handler, options); };
renderInspector();
field = realField;
handlers['Key type']('Toggle key');  // a toggle state never gets a Home Assistant step, as in the beta
result.states = key.states.map(state => state.actions.map(action => action.type));
return result;
''')
        self.assertEqual(found['shown'], ['Home Assistant step (beta firmware only)'])
        self.assertEqual(found['summary'], '1 Set variable: before → 2 Home Assistant step (beta firmware only) → 3 Set variable: after')
        self.assertTrue(found['saved'], 'the step, ha_state and the panel settings are saved as they are')
        self.assertEqual(found['offered'], ['Main › First › Copy'] * 2, 'the host refuses Home Assistant steps in a rule or on the rail')
        self.assertEqual(found['states'], [['set', 'set'], ['set', 'set']])


if __name__ == '__main__':
    unittest.main()
