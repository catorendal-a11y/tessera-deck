"""Remote devices (KDE Connect): which devices a setting means, the mixer faders and the five places the panel has, what the mute
button does, the media action and its validation. The system side is a fake with the four calls the platform packages offer."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
sys.path.insert(0, str(ROOT / 'tests'))
import cockpit  # noqa: E402
import remote_devices as remote  # noqa: E402
import tesserad as deck  # noqa: E402

PHONE = {'id': 'ce7eff39_d32c_4f52_a551_906c628a8485', 'name': 'OnePlus 12', 'type': 'phone'}
LAPTOP = {'id': 'a1b2c3_laptop', 'name': 'A laptop with a very long name', 'type': 'laptop'}


class FakeSystem:
    def __init__(self, devices=(PHONE,), volumes=None):
        self.found = list(devices)
        self.volumes = volumes or {PHONE['id']: 40, LAPTOP['id']: 75}
        self.written, self.actions, self.unreachable = [], [], set()

    def list_devices(self):
        return [dict(item) for item in self.found]

    def read_device(self, device):
        if device in self.unreachable:
            raise OSError('gone')
        return {'volume': self.volumes[device], 'playing': True, 'title': f'Song of {device[:3]}', 'artist': 'Band',
                'position': 60.0, 'duration': 240.0}

    def write_volume(self, device, level):
        self.written.append((device, level))
        self.volumes[device] = level

    def send_action(self, device, action):
        if device in self.unreachable:
            raise OSError('gone')
        self.actions.append((device, action))


class Case(unittest.TestCase):
    def use(self, **kwargs):
        system = FakeSystem(**kwargs)
        patcher = patch.object(remote, '_system', return_value=system)
        patcher.start()
        self.addCleanup(patcher.stop)
        remote._muted.clear()
        return system


class SelectTests(Case):
    def test_a_setting_means_none_the_first_all_or_one_device(self):
        self.use(devices=(PHONE, LAPTOP))
        found = remote.devices()
        self.assertEqual([item['id'] for item in remote.select(found, 'first')], [PHONE['id']])
        self.assertEqual(len(remote.select(found, 'all')), 2)
        self.assertEqual([item['name'] for item in remote.select(found, 'device', LAPTOP['id'])], [LAPTOP['name']])
        self.assertEqual([item['id'] for item in remote.select(found, 'device', found[1]['short'])], [LAPTOP['id']])
        self.assertEqual(remote.select(found, 'device', 'nobody'), [])
        self.assertEqual(remote.select([], 'first'), [])

    def test_a_device_gets_a_short_id_that_fits_the_panel(self):
        found = remote.devices() if self.use() else None
        fader = remote.FADER_PREFIX + found[0]['short']
        self.assertLessEqual(len(fader), cockpit.MAX_ID)
        self.assertRegex(fader, r'^remote:[0-9a-f]{10}$')


class FaderTests(Case):
    def test_off_gives_no_faders_and_a_device_gives_one_with_its_volume(self):
        self.use(devices=(PHONE, LAPTOP))
        self.assertEqual(remote.faders(None), [])
        self.assertEqual(remote.faders({'mode': 'off'}), [])
        first = remote.faders({'mode': 'first'})
        self.assertEqual([(item['name'], item['level'], item['muted']) for item in first], [('OnePlus 12', 40, False)])
        everyone = remote.faders({'mode': 'all'})
        self.assertEqual([item['level'] for item in everyone], [40, 75])
        self.assertLessEqual(len(everyone[1]['name']), remote.NAME_LENGTH)

    def test_the_faders_are_json_the_panel_accepts(self):
        self.use(devices=(PHONE, LAPTOP))
        payload = json.loads(cockpit.mixer_payload(remote.faders({'mode': 'all'})))['faders']
        for fader in payload:
            self.assertLessEqual(len(fader['id']), cockpit.MAX_ID)
            self.assertNotIn('"', fader['id'])
            self.assertEqual(set(fader), {'id', 'name', 'level', 'muted', 'color'})

    def test_a_device_that_does_not_answer_is_left_out_and_nothing_raises(self):
        system = self.use(devices=(PHONE, LAPTOP))
        system.unreachable.add(PHONE['id'])
        self.assertEqual([item['level'] for item in remote.faders({'mode': 'all'})], [75])

    def test_no_devices_no_faders(self):
        self.use(devices=())
        self.assertEqual(remote.faders({'mode': 'all'}), [])


class MixerTests(Case):
    LOCAL = [{'id': 'speaker', 'name': 'Master', 'level': 30, 'muted': False, 'color': '#58E09B'},
             {'id': 'app:a', 'name': 'A', 'level': 1, 'muted': False, 'color': '#1'},
             {'id': 'app:b', 'name': 'B', 'level': 2, 'muted': False, 'color': '#2'},
             {'id': 'app:c', 'name': 'C', 'level': 3, 'muted': False, 'color': '#3'},
             {'id': 'mic', 'name': 'Mic', 'level': 50, 'muted': False, 'mic': True, 'color': '#4DD0E1'}]

    def test_programs_make_room_for_the_remote_devices_and_the_speaker_and_the_microphone_stay(self):
        self.use(devices=(PHONE, LAPTOP))
        extra = remote.faders({'mode': 'all'})
        fitted = cockpit.fit_faders(self.LOCAL, extra)
        self.assertEqual([item['id'] for item in fitted][:1] + [item['id'] for item in fitted][-1:], ['speaker', 'mic'])
        self.assertEqual(len(fitted), cockpit.MAX_FADERS)
        self.assertEqual([item['name'] for item in fitted if item['id'].startswith('app:')], ['A'])
        self.assertEqual(len([item for item in fitted if item['id'].startswith('remote:')]), 2)

    def test_more_devices_than_places_never_push_out_the_microphone_or_the_speaker(self):
        self.use(devices=(PHONE, LAPTOP))
        many = [{'id': f'remote:{n:010d}', 'name': f'Device {n}', 'level': n, 'muted': False, 'color': '#FF8A65'} for n in range(6)]
        fitted = cockpit.fit_faders(self.LOCAL, many)
        self.assertEqual(len(fitted), cockpit.MAX_FADERS)
        self.assertEqual((fitted[0]['id'], fitted[-1]['id']), ('speaker', 'mic'))
        self.assertEqual([item['name'] for item in fitted[1:-1]], ['Device 0', 'Device 1', 'Device 2'])
        without_mic = cockpit.fit_faders([item for item in self.LOCAL if not item.get('mic')], many)
        self.assertEqual([item['id'] for item in without_mic][0], 'speaker')
        self.assertEqual(len(without_mic), cockpit.MAX_FADERS)

    def test_with_one_remote_device_two_programs_stay(self):
        self.use()
        fitted = cockpit.fit_faders(self.LOCAL, remote.faders({'mode': 'first'}))
        self.assertEqual([item['id'] for item in fitted], ['speaker', fitted[1]['id'], 'app:a', 'app:b', 'mic'])

    def test_read_mixer_adds_the_remote_faders_only_when_the_setting_asks_for_them(self):
        self.use()
        with patch('system_audio.read_mixer', return_value=list(self.LOCAL)):
            self.assertEqual(len(cockpit.read_mixer(None, True)), 5)
            self.assertEqual([item['id'][:7] for item in cockpit.read_mixer(None, True, {'mode': 'first'})].count('remote:'), 1)
            self.assertEqual(cockpit.read_mixer(None, True, {'mode': 'off'}), self.LOCAL)


class ControlTests(Case):
    def test_the_slider_sets_the_volume_of_that_device(self):
        system = self.use(devices=(PHONE, LAPTOP))
        short = remote.devices()[1]['short']
        remote.set_volume(remote.FADER_PREFIX + short, 130)
        self.assertEqual(system.written, [(LAPTOP['id'], 100)])

    def test_the_mute_button_sets_zero_and_the_second_press_gives_the_old_volume_back(self):
        system = self.use()
        fader = remote.faders({'mode': 'first'})[0]['id']
        remote.toggle_mute(fader)
        remote.toggle_mute(fader)
        self.assertEqual(system.written, [(PHONE['id'], 0), (PHONE['id'], 40)])

    def test_a_device_muted_before_the_host_started_comes_back_at_a_middle_volume(self):
        system = self.use(volumes={PHONE['id']: 0})
        remote.toggle_mute(remote.FADER_PREFIX + remote.devices()[0]['short'])
        self.assertEqual(system.written, [(PHONE['id'], remote.RESTORE_LEVEL)])

    def test_a_failed_write_keeps_what_a_mute_remembered(self):
        system = self.use()
        fader = remote.FADER_PREFIX + remote.devices()[0]['short']
        remote.toggle_mute(fader)  # 40 -> 0, 40 remembered
        write = system.write_volume

        def failing(device, level):
            raise OSError('gone')
        system.write_volume = failing
        with self.assertRaises(OSError):
            remote.toggle_mute(fader)  # the restore fails
        with self.assertRaises(OSError):
            remote.control_media('volumeup')
        with self.assertRaises(OSError):
            remote.set_volume(fader, 70)
        self.assertEqual(remote._muted, {remote.short_id(PHONE['id']): 40}, 'still remembered')
        system.write_volume = write
        remote.toggle_mute(fader)
        self.assertEqual(system.written[-1], (PHONE['id'], 40), 'the old volume comes back')
        self.assertEqual(remote._muted, {})

    def test_the_mute_button_does_not_guess_at_a_device_that_reports_no_volume(self):
        system = self.use()
        system.read_device = lambda device: {'volume': None, 'playing': False, 'title': '', 'artist': ''}
        with self.assertRaisesRegex(OSError, 'OnePlus 12: it does not report a volume'):
            remote.toggle_mute(remote.FADER_PREFIX + remote.devices()[0]['short'])
        self.assertEqual(system.written, [])

    def test_a_fader_of_a_device_that_is_not_reachable_is_an_error(self):
        self.use(devices=())
        with self.assertRaisesRegex(OSError, 'not reachable'):
            remote.set_volume('remote:0123456789', 10)

    def test_the_media_action_reaches_the_first_or_one_device_and_never_all_of_them(self):
        system = self.use(devices=(PHONE, LAPTOP))
        remote.control_media('playpause')
        remote.control_media('next', 'first')
        remote.control_media('previous', LAPTOP['id'])
        remote.control_media('stop', remote.devices()[1]['short'])
        self.assertEqual(system.actions, [(PHONE['id'], 'PlayPause'), (PHONE['id'], 'Next'), (LAPTOP['id'], 'Previous'),
                                          (LAPTOP['id'], 'Stop')])
        with self.assertRaisesRegex(OSError, 'not reachable'):
            remote.control_media('stop', 'all')  # a device called all would be a device, but "all" is no choice
        self.assertEqual(len(system.actions), 4)

    def test_volume_keys_move_the_volume_of_one_device_by_a_step_and_stay_between_0_and_100(self):
        system = self.use(devices=(PHONE, LAPTOP), volumes={PHONE['id']: 40, LAPTOP['id']: 98})
        remote.control_media('volumeup')
        remote.control_media('volumedown', 'first', 15)
        remote.control_media('volumeup', LAPTOP['id'], 10)
        remote.control_media('volumedown', LAPTOP['id'], 50)
        self.assertEqual(system.written, [(PHONE['id'], 45), (PHONE['id'], 30), (LAPTOP['id'], 100), (LAPTOP['id'], 50)])
        system.volumes[PHONE['id']] = 3
        remote.control_media('volumedown', 'first', 5)
        self.assertEqual(system.written[-1], (PHONE['id'], 0))

    def test_a_volume_key_forgets_the_volume_a_mute_remembered_and_needs_a_device_that_reports_one(self):
        system = self.use()
        fader = remote.faders({'mode': 'first'})[0]['id']
        remote.toggle_mute(fader)
        self.assertIn(remote.short_id(PHONE['id']), remote._muted)
        remote.control_media('volumeup')
        self.assertEqual(remote._muted, {}, 'the next mute starts from the new volume')
        system.read_device = lambda device: {'volume': None, 'playing': False, 'title': '', 'artist': ''}
        with self.assertRaisesRegex(OSError, 'OnePlus 12: it does not report a volume'):
            remote.control_media('volumeup')

    def test_the_media_action_says_what_is_wrong(self):
        system = self.use(devices=())
        with self.assertRaisesRegex(OSError, 'KDE Connect'):
            remote.control_media('playpause')
        system.found = [PHONE]
        with self.assertRaisesRegex(OSError, 'not reachable'):
            remote.control_media('playpause', 'someone_else')
        system.unreachable.add(PHONE['id'])
        with self.assertRaisesRegex(OSError, 'OnePlus 12'):
            remote.control_media('playpause')
        with self.assertRaises(ValueError):
            remote.control_media('rewind')


class StateTests(Case):
    def test_the_title_artist_and_playing_flag_of_the_first_device(self):
        self.use(devices=(PHONE, LAPTOP))
        self.assertEqual(remote.state(), {'remote:track': 'Song of ce7', 'remote:artist': 'Band', 'remote_playing': True,
                                          'remote_status': 'PLAYING', 'remote_position': 60.0, 'remote_duration': 240.0})

    def test_it_follows_the_first_connected_device_whatever_the_mixer_shows(self):
        """The same device a key's "device": "first" reaches, so the key and what it shows agree."""
        system = self.use(devices=(PHONE, LAPTOP))
        with patch.object(remote, 'faders', wraps=remote.faders):
            self.assertEqual([item['name'] for item in remote.faders({'mode': 'device', 'device': LAPTOP['id']})], ['A laptop with a'])
        self.assertEqual(remote.state()['remote:track'], 'Song of ce7')
        remote.control_media('playpause')
        self.assertEqual(system.actions, [(PHONE['id'], 'PlayPause')])

    def test_a_device_that_is_not_playing_clears_the_flag(self):
        system = self.use()
        system.read_device = lambda device: {'volume': 5, 'playing': False, 'title': 'Song', 'artist': 'Band'}
        self.assertFalse(remote.state()['remote_playing'])
        self.assertEqual(remote.state()['remote_status'], 'PAUSED')

    def test_nothing_reachable_gives_empty_text_and_no_flag(self):
        empty = remote.EMPTY_STATE
        self.use(devices=())
        self.assertEqual(remote.state(), empty)
        system = self.use()
        system.unreachable.add(PHONE['id'])
        self.assertEqual(remote.state(), empty)


class NeedsStateTests(Case):
    def test_the_device_is_only_asked_every_second_when_something_in_the_configuration_uses_it(self):
        base = {'default_profile': 'main', 'profiles': {'main': {'match': [], 'pages': {'main': [
            {'id': 1, 'label': 'Plain', 'icon': 'ok', 'actions': [{'type': 'remote_media', 'op': 'next'}]}]}}},
            'panel': {'remote': {'mode': 'first'}}}
        self.assertFalse(remote.needs_state(base), 'an action reads the device when it runs, a mixer fader has its own read')
        for name, change in (('a label', lambda key: key.update(label='$(remote:track)')),
                             ('a state', lambda key: key.update(bind='remote_playing', states=[{'label': 'a'}, {'label': 'b'}])),
                             ('a wide key', lambda key: key.update(span=2, live='remote_media'))):
            config = json.loads(json.dumps(base))
            change(config['profiles']['main']['pages']['main'][0])
            self.assertTrue(remote.needs_state(config), name)
        self.assertFalse(remote.needs_state(None))

    def test_the_answer_is_kept_for_the_same_configuration_and_made_again_for_a_new_one(self):
        config = {'profiles': {'main': {'pages': {'main': [{'label': 'Song $(remote:track)'}]}}}}
        self.assertTrue(remote.needs_state(config))
        config['profiles']['main']['pages']['main'][0]['label'] = 'Plain'
        self.assertTrue(remote.needs_state(config), 'the same object: not read again')
        self.assertFalse(remote.needs_state(json.loads(json.dumps(config))), 'a reloaded configuration is read again')

    def test_the_host_does_not_ask_without_a_use_and_does_with_one(self):
        from host_support import test_daemon
        daemon = test_daemon(port='TEST', no_focus=True)
        self.use()
        with patch.object(remote, 'state', return_value={'remote:track': 'Song'}) as asked:
            daemon.config = {'profiles': {}}
            self.assertEqual(daemon.pc._remote(), remote.EMPTY_STATE)
            asked.assert_not_called()
            daemon.config = {'profiles': {'main': {'pages': {'main': [{'label': '$(remote:track)'}]}}}, 'panel': {}}
            self.assertEqual(daemon.pc._remote(), {'remote:track': 'Song'})
            asked.assert_called_once()


class LiveTests(Case):
    def daemon(self):
        from host_support import test_daemon
        return test_daemon(port='TEST', no_focus=True)

    def test_a_wide_key_can_show_the_music_of_a_paired_device_and_not_the_pcs(self):
        daemon = self.daemon()
        daemon.pc._values.update({'title': 'On the laptop', 'artist': 'Local band', 'status': 'PLAYING', 'position': 10.0, 'duration': 100.0,
                                  'remote:track': 'On the phone', 'remote:artist': 'Phone band', 'remote_status': 'PLAYING',
                                  'remote_position': 60.0, 'remote_duration': 240.0})
        self.assertEqual(daemon.live_content('media'), {'label': 'On the laptop', 'sub': 'Local band', 'progress': 10})
        self.assertEqual(daemon.live_content('remote_media'), {'label': 'On the phone', 'sub': 'Phone band', 'progress': 25})

    def test_without_a_device_the_key_says_so_and_a_paused_one_says_paused(self):
        daemon = self.daemon()
        self.assertEqual(daemon.live_content('remote_media'), {'label': 'No music', 'sub': 'Nothing playing'})
        daemon.pc._values.update({'remote:track': 'Song', 'remote_status': 'PAUSED'})
        self.assertEqual(daemon.live_content('remote_media'), {'label': 'Song', 'sub': 'Paused'})

    def test_the_live_choice_is_validated_and_needs_a_wide_key(self):
        data = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        button = data['profiles']['main']['pages']['main'][0]
        button.update({'span': 2, 'live': 'remote_media'})
        data['profiles']['main']['pages']['main'] = [button]
        deck.validate_config(data)
        button.pop('span')
        with self.assertRaises(ValueError):
            deck.validate_config(data)


class EditorColorTests(unittest.TestCase):
    """The editor's color change for a toggle key (run in the editor's own JavaScript, as the other editor tests do)."""

    def test_states_that_share_a_color_keep_sharing_it_and_states_with_their_own_stay(self):
        from test_editor import run_editor
        found = run_editor(self, r"""
const fresh = () => ({default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [
  {id: 1, label: 'Remote', icon: 'ok', color: '#35D07F', actions: [], bind: 'remote_playing', states: [
    {label: 'Play', icon: 'ok', color: '#35D07F', actions: []}, {label: 'Pause', icon: 'ok', color: '#35D07F', actions: []}]},
  {id: 2, label: 'Mic', icon: 'ok', color: '#FFB74D', actions: [], bind: 'mic_muted', states: [
    {label: 'Mic live', icon: 'ok', color: '#35D07F', actions: []}, {label: 'Mic muted', icon: 'ok', color: '#FF5252', actions: []}]},
  {id: 3, label: 'Plain', icon: 'ok', color: '#35D07F', actions: []}]}}}});
const colors = key => [key.color, ...(key.states || []).map(state => state.color)];
const result = {};
config = fresh(); profile = 'Main'; page = 'First';
selected = 1; editState = 0; setColor('#112233'); result.shared = colors(current());
editState = 1; setColor('#445566'); result.sharedFromPause = colors(current());
selected = 2; editState = 0; setColor('#AA0000'); result.own = colors(current());
selected = 3; editState = 0; setColor('#00AA00'); result.plain = colors(current());
return result;
""")
        self.assertEqual(found, {'shared': ['#112233'] * 3, 'sharedFromPause': ['#445566'] * 3,
                                 'own': ['#FFB74D', '#AA0000', '#FF5252'], 'plain': ['#00AA00']})

    def test_the_group_other_devices_is_in_the_ready_made_tab_and_not_in_basics_while_the_step_list_still_has_the_action(self):
        from test_editor import run_editor
        packs = json.loads((ROOT / 'host/action_packs.json').read_text(encoding='utf-8'))['packs']
        found = run_editor(self, 'const packs = ' + json.dumps(packs) + r"""
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [{id: 1, label: 'A', icon: 'ok', actions: []}]}}}};
profile = 'Main'; page = 'First';
actionCatalog = {packs, templates: [], page_templates: []};
// what renderLibrary puts in the list: each group it builds is a {name, items} here
const original = category;
category = (name, items) => ({name, titles: items.map(item => String(item.title))});
const list = document.querySelector('#actions-library');
let shown = [];
list.append = (...nodes) => shown.push(...nodes.filter(node => node && node.name));
const groupsOf = (tab, search = '') => {
  libraryTab = tab; $('#action-search').value = search; shown = []; renderLibrary();
  return shown;
};
const result = {};
result.basics = groupsOf('basics').map(group => group.name);
result.ready = groupsOf('ready').map(group => group.name);
result.apps = groupsOf('apps').map(group => group.name);
result.readyOther = (groupsOf('ready').find(group => group.name === 'Other devices') || {}).titles;
result.search = groupsOf('basics', 'remote').flatMap(group => group.titles);
result.stepKind = Object.keys(kinds).includes('remote_media') && kinds.remote_media.group;
return result;
""")
        self.assertNotIn('Other devices', found['basics'])
        self.assertIn('Other devices', found['ready'])
        self.assertIn('Media', found['ready'])
        self.assertNotIn('Other devices', found['apps'])
        self.assertEqual(found['readyOther'], ['Remote play / pause (shows state)', 'Remote next track', 'Remote previous track',
                                               'Remote volume +', 'Remote volume -'])
        self.assertEqual(found['stepKind'], 'Other devices', 'the step list (the action type of a step) still offers it')
        self.assertNotIn('Remote media', found['search'], 'the raw action is not offered in the action list')
        self.assertEqual(sorted(found['search']), ['Remote next track', 'Remote play / pause (shows state)', 'Remote previous track',
                                                   'Remote volume +', 'Remote volume -'],
                         'a search shows each ready-made key once')

    def test_widening_a_remote_key_shows_the_music_of_the_device_and_other_keys_stay_as_they_were(self):
        from test_editor import run_editor
        found = run_editor(self, r"""
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [
  {id: 1, label: 'Remote', icon: 'ok', actions: [], bind: 'remote_playing', states: [
    {label: 'Play', icon: 'ok', actions: [{type: 'remote_media', op: 'playpause'}]}, {label: 'Pause', icon: 'ok', actions: [{type: 'remote_media', op: 'playpause'}]}]},
  {id: 7, label: 'Next', icon: 'ok', actions: [{type: 'remote_media', op: 'next'}]},
  {id: 13, label: 'Copy', icon: 'ok', actions: [{type: 'hotkey', keys: 'ctrl+c'}]}]}}}};
profile = 'Main'; page = 'First';
const result = {};
for (const id of [1, 7, 13]) { selected = id; setSpan(current(), 2); const key = current(); result[id] = [key.span, key.live]; }
selected = 1; setSpan(current(), 1); result.narrow = [current().span, current().live];
selected = 1; setSpan(current(), 2); current().live = 'media'; setSpan(current(), 3); result.kept = current().live;
result.name = liveName('remote_media');
return result;
""")
        self.assertEqual(found, {'1': [2, 'remote_media'], '7': [2, 'remote_media'], '13': [2, None], 'narrow': [None, None],
                                 'kept': 'media', 'name': 'Music of a paired device'})


class ValidationTests(unittest.TestCase):
    def config(self, **extra):
        data = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        data.update(extra)
        return data

    def test_the_remote_setting_and_the_action_are_validated(self):
        for good in ({'mode': 'off'}, {'mode': 'first'}, {'mode': 'all'}, {'mode': 'device', 'device': 'ce7eff39_d32c'}):
            deck.validate_config(self.config(panel={'remote': good}))
        for bad in ({'mode': 'some'}, {'mode': 'device'}, {'mode': 'first', 'device': 'x'}, {'mode': 'device', 'device': 'a b'},
                    {'extra': 1}, 'all'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                deck.validate_config(self.config(panel={'remote': bad}))

    def test_a_remote_media_key_is_validated(self):
        def check(action):
            data = self.config()
            data['profiles']['main']['pages']['main'][0]['actions'] = [action]
            deck.validate_config(data)
        for good in ({'type': 'remote_media', 'op': 'playpause'}, {'type': 'remote_media', 'op': 'next', 'device': 'first'},
                     {'type': 'remote_media', 'op': 'volumeup'}, {'type': 'remote_media', 'op': 'volumedown', 'step': 10},
                     {'type': 'remote_media', 'op': 'stop', 'device': 'a1b2c3_laptop'}):
            check(good)
        for bad in ({'type': 'remote_media'}, {'type': 'remote_media', 'op': 'rewind'}, {'type': 'remote_media', 'op': 5},
                    {'type': 'remote_media', 'op': 'volumeup', 'step': 0}, {'type': 'remote_media', 'op': 'volumeup', 'step': 51},
                    {'type': 'remote_media', 'op': 'volumeup', 'step': '5'}, {'type': 'remote_media', 'op': 'volumeup', 'step': True},
                    {'type': 'remote_media', 'op': 'play', 'device': 'all'}, {'type': 'remote_media', 'op': 'play', 'device': ''}, {'type': 'remote_media', 'op': 'play', 'device': 'a b'},
                    {'type': 'remote_media', 'op': 'play', 'device': 7}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                check(bad)

    def test_a_key_can_follow_the_remote_device_and_the_ready_made_key_does(self):
        data = self.config()
        button = data['profiles']['main']['pages']['main'][0]
        button['states'] = [{'label': 'Play', 'actions': [{'type': 'remote_media', 'op': 'playpause'}]},
                            {'label': 'Pause', 'actions': [{'type': 'remote_media', 'op': 'playpause'}]}]
        button['bind'] = 'remote_playing'
        deck.validate_config(data)
        catalog = json.loads((ROOT / 'host/action_packs.json').read_text(encoding='utf-8'))
        pack = next(item for item in catalog['packs'] if item['name'] == 'Remote play / pause (shows state)')
        self.assertEqual((pack['bind'], [state['label'] for state in pack['states']], [state['icon'] for state in pack['states']]),
                         ('remote_playing', ['Play', 'Pause'], ['lc:e13c', 'lc:e12e']))
        self.assertEqual(pack['actions'], [{'type': 'remote_media', 'op': 'playpause', 'device': 'first'}],
                         'dropped on a key that exists it adds the action; a new key takes the states (the editor does not add it twice)')
        self.assertEqual({action['type'] for state in pack['states'] for action in state['actions']}, {'remote_media'})

    def test_the_remote_keys_are_listed_under_media_and_under_other_devices(self):
        catalog = json.loads((ROOT / 'host/action_packs.json').read_text(encoding='utf-8'))
        remote_packs = [pack for pack in catalog['packs'] if pack['actions'] and pack['actions'][0].get('type') == 'remote_media'
                        or pack.get('states') and pack['states'][0]['actions'][0].get('type') == 'remote_media']
        self.assertEqual([pack['name'] for pack in remote_packs],
                         ['Remote play / pause (shows state)', 'Remote next track', 'Remote previous track', 'Remote volume +', 'Remote volume -'])
        for pack in remote_packs:
            self.assertEqual((pack['group'], pack.get('also')), ('Media', ['Other devices']), pack['name'])
        icons = {pack['name']: pack['icon'] for pack in remote_packs}
        self.assertEqual((icons['Remote previous track'], icons['Remote next track']), ('lc:e15f', 'lc:e160'), 'skip-back and skip-forward')
        self.assertEqual((icons['Remote volume +'], icons['Remote volume -']), ('plus', 'minus'), 'as the PC volume keys')
        self.assertEqual([pack['actions'][0]['op'] for pack in remote_packs[3:]], ['volumeup', 'volumedown'])
        ids = {item['id']: item['name'] for item in json.loads((ROOT / 'vendor/lucide/catalog.json').read_text(encoding='utf-8'))['icons']}
        self.assertEqual((ids['lc:e15f'], ids['lc:e160']), ('skip-back', 'skip-forward'))
        self.assertEqual([pack['name'] for pack in catalog['packs'] if 'also' in pack], [pack['name'] for pack in remote_packs])
        editor = (ROOT / 'host/editor/app.js').read_text(encoding='utf-8')
        general = next(line for line in editor.splitlines() if line.startswith('const GENERAL_GROUPS'))
        self.assertIn("'Other devices'", general, 'else the group lands in the Apps tab')

    def test_the_dry_run_says_what_the_key_does(self):
        from action_preview import preview
        text = [step['text'] for step in preview([{'type': 'remote_media', 'op': 'playpause'}, {'type': 'remote_media', 'op': 'volumeup'},
                                                  {'type': 'remote_media', 'op': 'volumedown', 'step': 10},
                                                  {'type': 'remote_media', 'op': 'next', 'device': 'ce7eff39_phone'}], {})['steps']]
        self.assertEqual(text, ['Play or pause on the first paired device that is reachable (KDE Connect)',
                                'Turn the volume of the first paired device that is reachable up by 5% (KDE Connect)',
                                'Turn the volume of the first paired device that is reachable down by 10% (KDE Connect)',
                                'Skip to the next track on a paired device (KDE Connect)'])


if __name__ == '__main__':
    unittest.main()
