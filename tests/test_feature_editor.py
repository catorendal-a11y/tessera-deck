"""Editor features that can be reached without a page: config rewrites, drafts and what a function writes into `config`."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_editor import host_takes, run_editor


class EditorFeatureTests(unittest.TestCase):
    def run_editor(self, script):
        return run_editor(self, script)

    def test_a_profile_step_keeps_its_page_through_renames_and_loses_it_on_delete(self):
        found = self.run_editor(r"""
const fresh = () => ({default_profile: 'Main', profiles: {
  Main: {match: [], pages: {First: [{id: 1, label: 'Go', icon: 'ok', actions: [{type: 'profile', profile: 'Work', page: 'Docs'}, {type: 'profile', profile: 'Main', page: 'First'}]}]}},
  Work: {match: [], pages: {Docs: [{id: 1, label: 'Go', icon: 'ok', actions: [{type: 'profile', profile: 'Work', page: 'Docs'}]}], Mail: []}}},
  panel: {shortcuts: [{type: 'actions', label: 'Go', icon: 'ok', actions: [{type: 'profile', profile: 'Work', page: 'Docs'}]}]},
  triggers: [{when: {type: 'startup'}, actions: [{type: 'profile', profile: 'Work', page: 'Docs'}]}]});
const seen = () => [config.profiles.Main.pages.First[0].actions, config.panel.shortcuts[0].actions, config.triggers[0].actions];
const result = {};
config = fresh(); profile = 'Work'; page = 'Docs'; selected = 1;
changePage('Papers');
result.rename = [seen(), config.profiles.Work.pages.Papers[0].actions];
config = fresh(); profile = 'Work'; page = 'Docs'; selected = 1;
changePage(null);
result.remove = [seen(), config.profiles.Work.pages.Mail];
config = fresh(); profile = 'Work'; page = 'Docs'; selected = 1;
renameProfile('Work', 'Job');
result.profile = [seen()[0], config.triggers[0].actions];
return result;
""")
        self.assertEqual(found['rename'][0][0], [{'type': 'profile', 'profile': 'Work', 'page': 'Papers'}, {'type': 'profile', 'profile': 'Main', 'page': 'First'}])
        self.assertEqual(found['rename'][0][1:], [[{'type': 'profile', 'profile': 'Work', 'page': 'Papers'}]] * 2)
        self.assertEqual(found['rename'][1], [{'type': 'profile', 'profile': 'Work', 'page': 'Papers'}])
        self.assertEqual(found['remove'][0][0], [{'type': 'profile', 'profile': 'Work'}, {'type': 'profile', 'profile': 'Main', 'page': 'First'}])
        self.assertEqual(found['remove'][0][1:], [[{'type': 'profile', 'profile': 'Work'}]] * 2)
        self.assertEqual(found['profile'][0][0], {'type': 'profile', 'profile': 'Job', 'page': 'Docs'})
        self.assertEqual(found['profile'][1], [{'type': 'profile', 'profile': 'Job', 'page': 'Docs'}])

    def test_changing_the_profile_of_a_step_clears_a_page_the_new_profile_lacks(self):
        found = self.run_editor(r"""
config = {default_profile: 'A', profiles: {A: {match: [], pages: {One: [], Two: []}}, B: {match: [], pages: {One: [], Three: []}}, C: {match: [], pages: {Four: []}}}};
const step = profile => ({type: 'profile', profile, page: 'One'});
const a = step('A'), b = step('A'), c = step('A');
switchProfileStep(a, 'B'); switchProfileStep(c, 'C');
const plain = {type: 'profile', profile: 'A'}; switchProfileStep(plain, 'C');
return [a, c, plain];
""")
        self.assertEqual(found, [{'type': 'profile', 'profile': 'B', 'page': 'One'}, {'type': 'profile', 'profile': 'C'}, {'type': 'profile', 'profile': 'C'}])

    def test_the_days_of_a_daily_rule_leave_no_key_when_all_or_none_are_ticked(self):
        found = self.run_editor(r"""
const days = ticked => { const when = {type: 'daily', at: '08:00', days: ['mon']}; setAutoDays(when, ticked); return when; };
return [days([]), days(['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat']), days(['sat', 'mon', 'wed']), days(['fri'])];
""")
        self.assertEqual(found, [{'type': 'daily', 'at': '08:00'}, {'type': 'daily', 'at': '08:00'},
                                 {'type': 'daily', 'at': '08:00', 'days': ['mon', 'wed', 'sat']}, {'type': 'daily', 'at': '08:00', 'days': ['fri']}])

    def test_a_kept_backup_says_so_and_the_button_toggles_it(self):
        found = self.run_editor(r"""
const calls = [];
api = async (path, body) => { calls.push([path, body]); return path === 'command/backups' ? {backups: []} : {name: 'kept-x.json'}; };
await keepBackup({name: 'a.json', kept: false});
await keepBackup({name: 'kept-b.json', kept: true});
return {calls: calls.filter(c => c[0] === 'command/keep-backup'), reloaded: calls.filter(c => c[0] === 'command/backups').length,
  plain: backupDetail({profiles: 2, buttons: 5, bytes: 100, kept: false}), kept: backupDetail({profiles: 2, buttons: 5, bytes: 100, kept: true})};
""")
        self.assertEqual(found['calls'], [['command/keep-backup', {'name': 'a.json', 'keep': True}], ['command/keep-backup', {'name': 'kept-b.json', 'keep': False}]])
        self.assertEqual(found['reloaded'], 2)
        self.assertNotIn('kept', found['plain'])
        self.assertTrue(found['kept'].endswith(' · kept'))

    def test_the_status_screen_offers_sixteen_readings_and_shows_eight_by_default(self):
        found = self.run_editor(r"""
config = {profiles: {}};
return {all: PANEL_STATS.map(s => s[0]), shown: panelChoice().stats};
""")
        self.assertEqual(found['all'], ['cpu_load', 'cpu_temp', 'ram', 'disk', 'gpu_load', 'gpu_temp', 'vram', 'net_down', 'net_up', 'uptime',
                                        'cpu_clock', 'cpu_power', 'gpu_power', 'gpu_clock', 'gpu_fan', 'fps'])
        self.assertEqual(found['shown'], found['all'][:8])

    def test_a_ready_made_key_that_shows_state_keeps_its_states_only_for_a_new_key(self):
        found = self.run_editor(r"""
actionCatalog = {packs: [{name: 'Mute mic', label: 'Mic', icon: 'mic', color: '#35D07F', actions: [], bind: 'mic_muted',
  states: [{label: 'Mic on', icon: 'mic', color: '#35D07F', actions: [{type: 'audio', target: 'mic', op: 'toggle'}]}, {label: 'Mic off', icon: 'mic-off', color: '#FF6B6B', actions: [{type: 'audio', target: 'mic', op: 'toggle'}]}]}]};
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [{id: 2, label: 'Old', icon: 'ok', actions: []}]}}}};
profile = 'Main'; page = 'First'; selected = 1; editState = 0;
addAction('pack:0');
const made = config.profiles.Main.pages.First.find(b => b.id === 1);
const result = {made: JSON.parse(JSON.stringify(made)), problem: keyProblem(made)};
addAction('pack:0', 2);
const dropped = config.profiles.Main.pages.First.find(b => b.id === 2);
result.dropped = Object.keys(dropped).sort();
return result;
""")
        key = found['made']
        self.assertEqual((key['label'], key['bind'], len(key['states']), found['problem']), ('Mic', 'mic_muted', 2, ''))
        self.assertEqual(key['actions'], [])
        self.assertEqual(found['dropped'], ['actions', 'icon', 'id', 'label'])

    def test_a_pack_without_a_label_or_states_makes_the_same_key_as_before(self):
        found = self.run_editor(r"""
actionCatalog = {packs: [{name: 'Lock PC', icon: 'lock', actions: [{type: 'hotkey', keys: 'win+l'}]}]};
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: []}}}};
profile = 'Main'; page = 'First'; selected = 1; editState = 0;
addAction('pack:0');
return config.profiles.Main.pages.First[0];
""")
        self.assertEqual(found, {'id': 1, 'label': 'Lock PC', 'icon': 'lock', 'color': '#35D07F', 'actions': [{'type': 'hotkey', 'keys': 'win+l'}]})

    def test_http_headers_and_timeouts_are_checked_like_the_host_does(self):
        found = self.run_editor(r"""
const http = extra => ({type: 'http', url: 'https://example.com', method: 'GET', ...extra});
const result = {
  text: headersText({'X-Token': 'a: b', Accept: 'json'}), empty: headersText(undefined), raw: headersText('oops'),
  parsed: parseHeaders('X-Token: $(env:T)\n\n Accept : json '), none: parseHeaders('  \n'), bad: parseHeaders('Accept json'), noName: parseHeaders(': x'),
  ok: stepProblem(http({headers: {A: 'b'}})), badLine: stepProblem(http({headers: parseHeaders('Accept json')})),
  timeouts: [stepProblem(http({timeout: 300})), stepProblem(http({timeout: 0})), stepProblem(http({timeout: 301})), stepProblem(http({timeout: 'x'})),
    stepProblem({type: 'shell', command: 'dir', timeout: 400}), stepProblem({type: 'shell', command: 'dir', timeout: 10})]};
const a = http({timeout: 5}); setTimeoutValue(a, ''); result.cleared = 'timeout' in a;
setTimeoutValue(a, '999'); result.high = a.timeout; setTimeoutValue(a, '0'); result.low = a.timeout; setTimeoutValue(a, '12'); result.set = a.timeout;
const b = http({}); setHeaders(b, 'A: b'); result.set_headers = b.headers; setHeaders(b, ''); result.removed = 'headers' in b;
return result;
""")
        self.assertEqual(found['text'], 'X-Token: a: b\nAccept: json')
        self.assertEqual((found['empty'], found['raw']), ('', 'oops'))
        self.assertEqual(found['parsed'], {'X-Token': '$(env:T)', 'Accept': 'json'})
        self.assertIsNone(found['none'])
        self.assertEqual((found['bad'], found['noName']), ('Accept json', ': x'))
        self.assertEqual(found['ok'], '')
        self.assertEqual(found['badLine'], 'write each header as Name: value')
        self.assertEqual(found['timeouts'], ['', 'use a timeout from 1 to 300 seconds', 'use a timeout from 1 to 300 seconds', 'use a timeout from 1 to 300 seconds',
                                              'use a timeout from 1 to 300 seconds', ''])
        self.assertEqual((found['cleared'], found['high'], found['low'], found['set']), (False, 300, 1, 12))
        self.assertEqual((found['set_headers'], found['removed']), ({'A': 'b'}, False))

    def test_quiet_hours_take_any_two_times_and_old_windows_show_their_times(self):
        found = self.run_editor(r"""
const night = (from, to) => nightFromValues(true, from, to, '20');
const fails = (...args) => { try { nightFromValues(...args); return ''; } catch (error) { return error.message; } };
return {across: night('22:00', '07:00'), same_day: night('13:15', '14:45'), off: nightFromValues(false, '22:00', '07:00', '20') === undefined,
  empty: fails(true, '', '07:00', '20'), equal: fails(true, '08:00', '08:00', '20')};
""")
        self.assertEqual(found['across'], {'from': '22:00', 'to': '07:00', 'brightness': 20})
        self.assertEqual(found['same_day'], {'from': '13:15', 'to': '14:45', 'brightness': 20})
        self.assertTrue(found['off'])
        self.assertEqual(found['empty'], 'Choose a start and an end time for quiet hours.')
        self.assertEqual(found['equal'], 'Quiet hours need different start and end times.')

    def test_moving_a_key_to_another_page_reports_a_full_page(self):
        found = self.run_editor(r"""
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [{id: 3, label: 'A', icon: 'ok', actions: []}],
  Full: Array.from({length: 18}, (_, i) => ({id: i + 1, label: 'K', icon: 'ok', actions: []})), Free: []}}}};
profile = 'Main'; page = 'First'; selected = 3;
moveToPage(3, 'Full');
const full = String(document.querySelector('#toast').textContent), still = config.profiles.Main.pages.First.length;
moveToPage(3, 'Free');
return {full, still, moved: config.profiles.Main.pages.Free.map(b => b.id), other: otherPages()};
""")
        self.assertEqual(found['full'], 'Page “Full” has no free slot for this key.')
        self.assertEqual((found['still'], found['moved'], found['other']), (1, [3], ['Full', 'Free']))


    def test_the_firmware_dialog_offers_the_packages_for_the_boards_the_panel_can_be(self):
        found = run_editor(self, r"""
const packages = [{path: 'v3-9', board: 'tessera-p4-v3', version: '1.2.9'}, {path: 'p4-9', board: 'tessera-p4', version: '1.2.9'},
  {path: 'crow-9', board: 'tessera-p4-crowpanel7', version: '1.2.9'}, {path: 'old', version: '1.0.0'}, {path: 'bad', error: 'damaged'}];
const pick = (boards, all) => { const c = firmwareChoices(packages, boards, all); return [c.shown.map(p => p.path), c.newest?.path || null, c.hidden]; };
return {v3: pick(['tessera-p4-v3']), v1: pick(['tessera-p4', 'tessera-p4-crowpanel7']), unknown: pick(null),
  all: pick(['tessera-p4-v3'], true), none: pick(['tessera-s3-ws7']), chip: chipName('esp32p4')};
""")
        self.assertEqual(found, {
            'v3': [['v3-9'], 'v3-9', 3],  # one board fits the chip: its package is chosen
            'v1': [['p4-9', 'crow-9', 'old'], None, 1],  # two boards share the chip: the user chooses
            'unknown': [['v3-9', 'p4-9', 'crow-9', 'old'], None, 0],
            'all': [['v3-9', 'p4-9', 'crow-9', 'old'], 'v3-9', 0],
            'none': [[], None, 4], 'chip': 'ESP32-P4'})

    def test_the_firmware_dialog_says_how_the_package_relates_to_the_panel(self):
        found = run_editor(self, r"""
const panel = {connected: true, firmware: '1.2.1'};
return {order: [versionOrder('1.2.3', '1.10.0'), versionOrder('1.2.3', '1.2.3'), versionOrder('2.0', '1.9.9'), versionOrder('1.2.3', null)],
  older: firmwareNote({version: '1.2.0'}, panel, '1.2.3'), same: firmwareNote({version: '1.2.1'}, panel, '1.2.1'),
  newer: firmwareNote({version: '1.2.3'}, panel, '1.2.3'), blank: firmwareNote({version: '1.2.0'}, {connected: false}, '1.2.3'),
  kept: firmwareNote({version: '1.2.0'}, panel, '1.2.3', {version: '1.2.3'}), none: firmwareNote(undefined, panel, '1.2.3')};
""")
        self.assertEqual(found, {
            'order': [-1, 0, 1, 0],
            'older': 'This package is older than the firmware on the panel (1.2.1). Installing it goes back to 1.2.0. '
                     'There is no firmware package for Tessera 1.2.3 here. Check for updates downloads it.',
            'same': 'The panel already has 1.2.1.', 'newer': '',
            'kept': 'This package is older than the firmware on the panel (1.2.1). Installing it goes back to 1.2.0.',
            'blank': 'There is no firmware package for Tessera 1.2.3 here. Check for updates downloads it.', 'none': ''})


    def test_a_step_on_a_held_key_turns_hold_to_confirm_off(self):
        found = self.run_editor(r"""
const key = () => ({id: 1, label: 'Off', icon: 'ok', confirm: true, actions: [{type: 'hotkey', keys: 'a'}]});
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [key()]}}}};
profile = 'Main'; page = 'First'; selected = 1; history = [];
activeActions(); editList = 'hold_actions';
addAction('hotkey', 1);
const held = config.profiles.Main.pages.First[0], toast1 = String(document.querySelector('#toast').textContent);
config.profiles.Main.pages.First = [key()]; editList = 'actions';
addAction('hotkey', 1);
return {held: [held.confirm ?? null, held.hold_actions.length], toast: toast1, tap: config.profiles.Main.pages.First[0].confirm};
""")
        self.assertEqual(found['held'], [None, 1])
        self.assertIn('Hold to confirm was turned off', found['toast'])
        self.assertTrue(found['tap'])

    def test_a_refused_move_to_slot_draws_the_inspector_again(self):
        found = self.run_editor(r"""
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [{id: 2, label: 'W', icon: 'ok', span: 2, actions: []}]}}}};
profile = 'Main'; page = 'First'; selected = 2;
let drawn = 0; renderInspector = () => { drawn++; };
moveSlot(2, 6);  // a wide key does not fit across the end of a row
return {drawn, still: config.profiles.Main.pages.First[0].id, selected};
""")
        self.assertEqual(found, {'drawn': 1, 'still': 2, 'selected': 2})

    def test_cancelling_a_new_subpage_takes_the_folder_key_back(self):
        found = self.run_editor(r"""
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [], Other: []}}}};
profile = 'Main'; page = 'First'; selected = 1; history = []; future = [];
let closed = null; dialog = () => {};
document.querySelector('#form-dialog').addEventListener = (name, fn) => { closed = fn; };
addAction('folder');
const made = config.profiles.Main.pages.First.length;
closed();
return {made, left: config.profiles.Main.pages.First.length};
""")
        self.assertEqual(found, {'made': 1, 'left': 0})

    def test_the_rail_refuses_a_shortcut_that_copied_an_unfinished_step(self):
        found = self.run_editor(r"""
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: []}}}}; profile = 'Main'; page = 'First';
const toasts = [];
toast = message => toasts.push(message);
const apply = actions => {
  railDraft = {order: ['keys'], on: new Set(['keys']), shortcuts: [{type: 'actions', label: 'Go', icon: 'lc:e0ff', actions}]};
  document.querySelector('#rail-apply').onclick();
  return config.panel?.shortcuts ?? null;
};
const unfinished = apply([{type: 'http', method: 'GET', url: ''}]);
const told = [...toasts];
const finished = apply([{type: 'http', method: 'GET', url: 'https://example.com'}]);
return {unfinished, told, finished};
""")
        self.assertIsNone(found['unfinished'])
        self.assertIn('not finished', found['told'][0])
        self.assertEqual(found['finished'], [{'type': 'actions', 'label': 'Go', 'icon': 'lc:e0ff', 'actions': [{'type': 'http', 'method': 'GET', 'url': 'https://example.com'}]}])

    def test_rail_and_automatic_actions_apply_with_a_page_step_after_the_first(self):
        found = self.run_editor(r"""
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [], Other: []}}}}; profile = 'Main'; page = 'First';
toast = () => {};
const steps = [{type: 'hotkey', keys: 'ctrl+c'}, {type: 'page', page: 'Other'}, {type: 'folder', page: 'Other'}];
railDraft = {order: ['keys'], on: new Set(['keys']), shortcuts: [{type: 'actions', label: 'Go', icon: 'lc:e0ff', actions: steps}]};
document.querySelector('#rail-apply').onclick();
autoDraft = [{when: {type: 'startup'}, actions: steps}];
document.querySelector('#auto-apply').onclick();
return {rail: config.panel?.shortcuts?.length ?? null, auto: config.triggers?.length ?? null};
""")
        self.assertEqual(found, {'rail': 1, 'auto': 1})

    def test_a_key_pasted_into_a_profile_without_its_page_stays_a_draft(self):
        found = self.run_editor(r"""
const folder = {id: 1, label: 'Status', icon: 'folder', actions: [{type: 'folder', page: 'status'}]};
config = {default_profile: 'main', profiles: {
  main: {match: [], pages: {first: [folder], status: []}},
  coding: {match: [], pages: {first: []}}}};
profile = 'main'; page = 'first'; selected = 1; history = []; future = [];
copyButton();
profile = 'coding'; page = 'first'; selected = 2;
pasteButton();
const sent = savable(config);
return {drafts: draftProblems(), sent: sent.profiles.coding.pages.first.map(k => k.actions), kept: savable(config).profiles.main.pages.first[0].actions};
""")
        self.assertEqual([(d['profile'], d['id']) for d in found['drafts']], [('coding', 2)])
        self.assertEqual(found['sent'], [[]])
        self.assertEqual(found['kept'], [{'type': 'folder', 'page': 'status'}])

    def test_deleting_a_profile_removes_rail_and_trigger_steps_to_pages_only_it_had(self):
        found = self.run_editor(r"""
const go = type => ({type, page: 'Lobby'}), shared = {type: 'page', page: 'Home'};
config = {default_profile: 'Main', profiles: {
  Main: {match: [], pages: {Home: []}}, Games: {match: [], pages: {Lobby: [], Home: []}}},
  panel: {shortcuts: [{type: 'actions', label: 'Go', icon: 'ok', actions: [go('page')]}, {type: 'actions', label: 'Home', icon: 'ok', actions: [shared]}]},
  triggers: [{when: {type: 'startup'}, actions: [go('folder'), {type: 'hotkey', keys: 'a'}]}]};
profile = 'Games'; page = 'Lobby'; selected = 1; history = []; future = [];
deleteProfile();
return {shortcuts: config.panel.shortcuts, triggers: config.triggers};
""")
        self.assertEqual(found['shortcuts'], [{'type': 'actions', 'label': 'Home', 'icon': 'ok', 'actions': [{'type': 'page', 'page': 'Home'}]}])
        self.assertEqual(found['triggers'], [{'when': {'type': 'startup'}, 'actions': [{'type': 'hotkey', 'keys': 'a'}]}])

    def test_run_now_on_a_toggle_key_asks_about_every_state_it_might_press(self):
        found = self.run_editor(r"""
const key = {id: 1, label: 'Mode', icon: 'ok', states: [
  {label: 'A', icon: 'ok', actions: [{type: 'hotkey', keys: 'ctrl+c'}]},
  {label: 'B', icon: 'ok', actions: [{type: 'shell', command: 'echo hi'}]}]};
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [key]}}}};
profile = 'Main'; page = 'First'; selected = 1; editState = 0; history = []; future = [];
dashboard = {device: {connected: true}};
const asked = [], calls = [];
askDialog = async (title, message) => { asked.push(message); return false; };
api = async (path, data) => { calls.push(path); return path === 'command/dryrun' ? {actions: {steps: [], wait_seconds: 0}} : {message: 'ok', revision: 'r'}; };
await testButton();
await document.querySelector('#test-run').onclick();
await settle();
return {asked, ran: calls.includes('command/run-key')};
""")
        self.assertEqual(len(found['asked']), 1)
        self.assertIn('runs a command', found['asked'][0])
        self.assertFalse(found['ran'])

    def test_a_step_the_host_refuses_for_its_size_or_values_stays_a_draft(self):
        cases = {
            'sameToggle': {'type': 'toggle', 'variable': 'mode', 'values': ['1', '1']},
            'longToggle': {'type': 'toggle', 'variable': 'mode', 'values': ['a', 'x' * 65]},
            'okToggle': {'type': 'toggle', 'variable': 'mode', 'values': ['a', 'x' * 64]},
            'okDefaultToggle': {'type': 'toggle', 'variable': 'mode'},
            'longNotify': {'type': 'timer', 'name': 't', 'op': 'start', 'seconds': 5, 'notify': 'x' * 121},
            'okNotify': {'type': 'timer', 'name': 't', 'op': 'start', 'seconds': 5, 'notify': 'x' * 120},
            'longSet': {'type': 'set', 'variable': 'v', 'value': 'x' * 1001},
            'okSet': {'type': 'set', 'variable': 'v', 'value': 'x' * 1000},
            'longWindow': {'type': 'window', 'op': 'minimize', 'process': 'x' * 261},
            'okWindow': {'type': 'window', 'op': 'minimize', 'process': 'x' * 260},
            'longOpen': {'type': 'open', 'target': 'notepad.exe', 'process': 'x' * 261},
            'farMouse': {'type': 'mouse', 'op': 'move', 'x': 20001, 'y': 0},
            'farMouseY': {'type': 'mouse', 'op': 'moveto', 'x': 0, 'y': -20001},
            'okMouse': {'type': 'mouse', 'op': 'moveto', 'x': -20000, 'y': 20000}}
        emoji = '\U0001F600'  # one character for Python, two for JavaScript's length
        for name, limit, step in (('Toggle', 64, lambda s: {'type': 'toggle', 'variable': 'mode', 'values': ['a', s]}),
                                  ('Notify', 120, lambda s: {'type': 'timer', 'name': 't', 'op': 'start', 'notify': s}),
                                  ('Set', 1000, lambda s: {'type': 'set', 'variable': 'v', 'value': s}),
                                  ('Window', 260, lambda s: {'type': 'window', 'op': 'minimize', 'process': s})):
            cases['okEmoji' + name], cases['longEmoji' + name] = step(emoji * limit), step(emoji * (limit + 1))
        expected = {name: host_takes(step) for name, step in cases.items()}
        self.assertEqual(expected, {name: name.startswith('ok') for name in cases}, 'the cases cover both sides of each limit')
        found = self.run_editor('return Object.fromEntries(Object.entries(' + json.dumps(cases)
                                + ').map(([name, step]) => [name, !stepProblem(step)]));')
        self.assertEqual(found, expected)

    def test_the_editor_does_not_follow_the_panel_while_a_field_in_the_inspector_has_focus(self):
        found = self.run_editor(r"""
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [{id: 1, label: 'A', icon: 'ok', actions: []}], Second: [{id: 1, label: 'B', icon: 'ok', actions: []}]}}}};
profile = 'Main'; page = 'First'; selected = 1; history = []; future = [];
dashboard = {running: true, device: {connected: true, profile: 'Main', page: 'Second'}};
const find = document.querySelector, field = {dataset: {}};  // stands in for a text field in the inspector; renderGrid reads its dataset
document.querySelector = selector => selector === 'dialog[open]' ? null : find(selector);
find('#inspector').contains = node => node === field;
document.activeElement = field;
followDevice();
const typing = page;
document.activeElement = null;
followDevice();
return {typing, after: page};
""")
        self.assertEqual(found, {'typing': 'First', 'after': 'Second'})


if __name__ == '__main__':
    unittest.main()
