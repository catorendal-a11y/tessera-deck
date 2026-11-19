"""PC state binding: mic/speaker/media flags, label variables and the audio action; no audio hardware."""
import os
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, PropertyMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import pc_state
from platform_windows import audio as win_audio, media as win_media
import tesserad as deck
import host_support  # noqa: E402


def audio(volume=40, speaker=False, mic=False):
    return lambda: {'volume': volume, 'speaker_muted': speaker, 'mic_muted': mic}


def media(title='', artist='', status=''):
    return lambda: {'title': title, 'artist': artist, 'status': status}


def failing():
    raise OSError('no device')


class RemoteVariableTests(unittest.TestCase):
    def test_the_title_and_artist_of_a_remote_device_are_variables(self):
        state = pc_state.PcState(audio(), media(), remote=lambda: {'remote:track': 'Home', 'remote:artist': 'Band'})
        state.poll()
        variables = state.variables()
        self.assertEqual((variables['remote:track'], variables['remote:artist']), ('Home', 'Band'))
        self.assertEqual(variables['pc:track'], 'No music', 'the PC keeps its own')

    def test_a_key_can_follow_whether_the_remote_device_plays(self):
        playing = {'remote:track': 'Home', 'remote:artist': 'Band', 'remote_playing': True}
        state = pc_state.PcState(audio(), media(), remote=lambda: playing)
        self.assertIn('remote_playing', pc_state.FLAG_SOURCES)
        state.poll()
        self.assertTrue(state.flag('remote_playing'))
        playing['remote_playing'] = False
        state.poll()
        self.assertFalse(state.flag('remote_playing'))

    def test_without_a_remote_reader_or_when_it_fails_they_are_empty_and_the_rest_keeps_working(self):
        for remote in (None, failing):
            state = pc_state.PcState(audio(50), media('Song', 'Band', 'PLAYING'), remote=remote)
            state.poll()
            variables = state.variables()
            self.assertEqual((variables['remote:track'], variables['pc:track']), ('', 'Song'))


class PcStateTests(unittest.TestCase):
    def test_flags_and_variables_follow_the_readers(self):
        state = pc_state.PcState(audio(40, mic=True), media('Song', 'Band', 'PLAYING'))
        state.poll()
        self.assertTrue(state.flag('mic_muted'))
        self.assertFalse(state.flag('speaker_muted'))
        self.assertTrue(state.flag('media_playing'))
        variables = state.variables()
        self.assertEqual(variables['pc:volume'], '40%')
        self.assertEqual(variables['pc:mic'], 'MUTED')
        self.assertEqual(variables['pc:speaker'], 'ON')
        self.assertEqual(variables['pc:media'], 'Band - Song')

    def test_a_failing_source_keeps_the_last_value_and_reports_the_error(self):
        state = pc_state.PcState(audio(55), media('Song', '', 'PAUSED'))
        state.poll()
        state._audio = failing
        state.poll()
        self.assertEqual(state.variables()['pc:volume'], '55%')
        self.assertIn('no device', state.error)
        self.assertFalse(state.flag('media_playing'))

    def test_an_unexpected_library_error_is_recorded_not_raised(self):
        def changed_api():
            raise AttributeError('no GetMasterVolume')
        state = pc_state.PcState(changed_api, media('Song', '', 'PLAYING'))
        state.poll()
        self.assertIn('GetMasterVolume', state.error)
        self.assertTrue(state.flag('media_playing'))

    def test_unknown_audio_commands_are_rejected(self):
        with self.assertRaises(ValueError):
            win_audio.control_audio('headset', 'toggle')
        with self.assertRaises(ValueError):
            win_audio.control_audio('mic', 'explode')


class AudioControlTests(unittest.TestCase):
    def fake(self, volume=0.4, muted=False):
        state = {'volume': volume, 'muted': muted}
        control = win_audio._Control(lambda: state['muted'], lambda value, _: state.update(muted=bool(value)),
                                    lambda: state['volume'], lambda value, _: state.update(volume=value))
        return control, state

    def test_mute_toggle_and_volume_operations(self):
        control, state = self.fake()
        win_audio.apply_operation(control, 'toggle')
        self.assertTrue(state['muted'])
        win_audio.apply_operation(control, 'unmute')
        self.assertFalse(state['muted'])
        win_audio.apply_operation(control, 'volume', 70)
        self.assertEqual(state['volume'], 0.7)
        win_audio.apply_operation(control, 'up', None, 10)
        self.assertAlmostEqual(state['volume'], 0.8)
        win_audio.apply_operation(control, 'down', None, 50)
        self.assertAlmostEqual(state['volume'], 0.3)
        win_audio.apply_operation(control, 'down', None, 50)
        self.assertEqual(state['volume'], 0.0, 'the volume never goes below 0')
        win_audio.apply_operation(control, 'volume', 100)
        win_audio.apply_operation(control, 'up', None, 50)
        self.assertEqual(state['volume'], 1.0, 'nor above 100')

    @unittest.skipIf(importlib.util.find_spec('comtypes') is None, 'comtypes is not installed')
    def test_an_app_target_controls_every_session_of_that_program_and_explains_silence(self):
        first, first_state = self.fake()
        second, second_state = self.fake()
        with patch.object(win_audio, '_app_controls', return_value=[first, second]) as found:
            win_audio.control_audio('app:Spotify.exe', 'mute')
        found.assert_called_once_with('Spotify.exe')
        self.assertTrue(first_state['muted'] and second_state['muted'])
        with patch.object(win_audio, '_app_controls', return_value=[]):
            with self.assertRaises(OSError) as raised:
                win_audio.control_audio('app:ghost.exe', 'mute')
        self.assertIn('not playing sound', str(raised.exception))

    @unittest.skipIf(importlib.util.find_spec('comtypes') is None, 'comtypes is not installed')
    def test_toggling_an_app_with_mixed_sessions_mutes_them_all_then_unmutes_them_all(self):
        first, first_state = self.fake(muted=True)
        second, second_state = self.fake(muted=False)
        with patch.object(win_audio, '_app_controls', return_value=[first, second]):
            win_audio.control_audio('app:Discord.exe', 'toggle')
            self.assertTrue(first_state['muted'] and second_state['muted'])
            win_audio.control_audio('app:Discord.exe', 'toggle')
        self.assertFalse(first_state['muted'] or second_state['muted'])

    def test_a_program_name_needs_exe_on_windows_only(self):
        action = {'target': 'app:firefox'}
        if os.name == 'nt':
            with self.assertRaises(ValueError):
                pc_state.check_audio(action)
        else:
            pc_state.check_audio(action)
            pc_state.check_audio({'target': 'app:Firefox.exe'})  # a Windows profile still validates

    def test_audio_actions_are_validated(self):
        for good in ({'target': 'mic'}, {'target': 'speaker', 'op': 'volume', 'value': 30},
                     {'target': 'app:chrome.exe', 'op': 'up', 'step': 10}):
            pc_state.check_audio(good)
        for bad in ({'target': 'tv'}, {'target': 'app:bad name.exe'}, {'target': 'app:../x.exe'}, {'target': 'mic', 'op': 'explode'},
                    {'target': 'mic', 'op': 'volume'}, {'target': 'mic', 'op': 'volume', 'value': 101},
                    {'target': 'mic', 'op': 'up', 'step': 0}, {'target': 'mic', 'op': 'up', 'step': 1.5}, {}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                pc_state.check_audio(bad)


class DaemonBindingTests(unittest.TestCase):
    def daemon(self, audio_reader=None, media_reader=None):
        daemon = host_support.test_daemon(port='TEST', no_focus=True)
        daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
        daemon.pc = pc_state.PcState(audio_reader or audio(), media_reader or media())
        daemon.pc.poll()
        daemon.profile, daemon.page = 'main', 'audio'
        return daemon

    def test_mic_button_shows_the_state_of_the_microphone(self):
        live = {b['id']: b for b in self.daemon(audio(mic=False)).current_buttons()}[8]
        muted = {b['id']: b for b in self.daemon(audio(mic=True)).current_buttons()}[8]
        self.assertEqual((live['label'], live['color']), ('Mic live', '#35D07F'))
        self.assertEqual((muted['label'], muted['color']), ('Mic muted', '#FF5252'))

    def test_pressing_a_bound_button_toggles_audio_without_cycling_its_state(self):
        daemon = self.daemon()
        with patch.object(deck, 'control_audio') as mute:
            self.assertTrue(daemon.dispatch_press(8))
        mute.assert_called_once_with('mic', 'toggle', None, 5)
        self.assertEqual(daemon.button_states, {})

    def test_media_labels_use_pc_variables(self):
        daemon = self.daemon(audio(30), media('Blue', 'Eiffel 65', 'PLAYING'))
        labels = {item['id']: item['label'] for item in daemon.current_buttons()}
        self.assertEqual(labels[15], 'Blue')
        self.assertEqual(labels[16], 'Vol 30%')

    def test_validation_of_bind_and_audio_actions(self):
        config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        broken = (lambda b: b.update(bind='nonsense'),
                  lambda b: b.pop('states'),
                  lambda b: b['states'][0]['actions'].__setitem__(0, dict(type='audio', target='tv')))
        for mutate in broken:
            candidate = copy.deepcopy(config)
            mutate(next(b for b in candidate['profiles']['main']['pages']['audio'] if b['label'] == 'Mic'))
            with self.assertRaises(ValueError):
                deck.validate_config(candidate)
        deck.validate_config(config)


class FakeMode(int):
    """Stands in for the winrt repeat enum: int-like, built again from a number."""


class FakeSession:
    def __init__(self, shuffle=False, mode=None, shuffle_enabled=True, repeat_enabled=True):
        self.info = Mock(is_shuffle_active=shuffle, auto_repeat_mode=mode,
                         controls=Mock(is_shuffle_enabled=shuffle_enabled, is_repeat_enabled=repeat_enabled))
        self.calls = []

    def get_playback_info(self):
        return self.info

    async def try_change_shuffle_active_async(self, value):
        self.calls.append(('shuffle', value))
        return True

    async def try_change_auto_repeat_mode_async(self, value):
        self.calls.append(('repeat', int(value)))
        return True


class MediaReadTests(unittest.TestCase):
    def test_a_failing_repeat_read_keeps_title_playing_state_and_shuffle(self):
        import asyncio

        class BrokenInfo:  # what a real player gives without winrt-Windows.Media installed
            playback_status = 4

            @property
            def auto_repeat_mode(self):
                raise ModuleNotFoundError("No module named 'winrt.windows.media'")
            is_shuffle_active = True

        async def properties():
            return Mock(title='Song', artist='Band')
        session = Mock(try_get_media_properties_async=properties, get_playback_info=lambda: BrokenInfo(),
                       get_timeline_properties=Mock(side_effect=OSError('no timeline')))
        manager = Mock(get_current_session=lambda: session)
        reader = win_media.MediaReader()
        reader._manager = manager
        result = asyncio.run(reader._read(None))
        self.assertEqual((result['title'], result['artist'], result['status']), ('Song', 'Band', 'PLAYING'))
        self.assertEqual((result['shuffle'], result['repeat']), (True, ''))


class MediaOptionTests(unittest.TestCase):
    def run_option(self, session, operation):
        import asyncio
        return asyncio.run(win_media._change_media_option(session, operation))

    def test_shuffle_flips_and_repeat_cycles_off_all_one(self):
        session = FakeSession(shuffle=False)
        self.assertTrue(self.run_option(session, 'shuffle'))
        self.assertEqual(session.calls, [('shuffle', True)])
        for mode, expected in ((0, 2), (2, 1), (1, 0)):
            session = FakeSession(mode=FakeMode(mode))
            self.run_option(session, 'repeat')
            self.assertEqual(session.calls, [('repeat', expected)])

    def test_a_player_without_the_option_is_left_alone(self):
        for session in (FakeSession(shuffle=None), FakeSession(shuffle_enabled=False)):
            self.assertFalse(self.run_option(session, 'shuffle'))
            self.assertEqual(session.calls, [])
        for session in (FakeSession(mode=None), FakeSession(mode=FakeMode(0), repeat_enabled=False)):
            self.assertFalse(self.run_option(session, 'repeat'))
            self.assertEqual(session.calls, [])

    def test_a_press_that_changes_nothing_says_why(self):
        import types

        def control(session, operation):
            async def request_async():
                return Mock(get_current_session=lambda: session)
            manager = types.SimpleNamespace(request_async=request_async)
            module = types.SimpleNamespace(GlobalSystemMediaTransportControlsSessionManager=manager)
            with patch.dict(sys.modules, {'winrt.windows.media.control': module}):
                win_media.control_media(operation)

        with self.assertRaisesRegex(OSError, 'No player is open'):
            control(None, 'repeat')
        with self.assertRaisesRegex(OSError, 'does not offer shuffle'):  # Windows Media Player has no shuffle here
            control(FakeSession(shuffle_enabled=False), 'shuffle')
        session = FakeSession(mode=FakeMode(0))
        control(session, 'repeat')
        self.assertEqual(session.calls, [('repeat', 2)])

    def test_a_missing_repeat_package_is_named_in_the_error(self):
        session = FakeSession()
        type(session.info).auto_repeat_mode = PropertyMock(side_effect=ModuleNotFoundError("No module named 'winrt.windows.media'"))
        with self.assertRaisesRegex(OSError, 'winrt-Windows.Media'):
            self.run_option(session, 'repeat')
        self.assertEqual(session.calls, [])

    def test_variables_and_flags_follow_the_player(self):
        def reading(shuffle, repeat):
            return lambda: {'title': 'Song', 'artist': '', 'status': 'PLAYING', 'shuffle': shuffle, 'repeat': repeat}
        state = pc_state.PcState(audio(), reading(True, 'list'))
        state.poll()
        self.assertEqual((state.variables()['pc:shuffle'], state.variables()['pc:repeat']), ('ON', 'ALL'))
        self.assertTrue(state.flag('media_shuffle') and state.flag('media_repeat'))
        state = pc_state.PcState(audio(), reading(False, 'track'))
        state.poll()
        self.assertEqual((state.variables()['pc:shuffle'], state.variables()['pc:repeat']), ('OFF', 'ONE'))
        self.assertFalse(state.flag('media_shuffle'))
        state = pc_state.PcState(audio(), media('Song', '', 'PLAYING'))  # a player that reports neither
        state.poll()
        self.assertEqual((state.variables()['pc:shuffle'], state.variables()['pc:repeat']), ('', ''))
        self.assertFalse(state.flag('media_repeat'))

    def test_the_action_is_validated_and_bindable(self):
        config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        page = config['profiles']['main']['pages']['main']
        page[0]['actions'] = [{'type': 'media', 'op': 'shuffle'}, {'type': 'media', 'op': 'repeat'}]
        deck.validate_config(config)
        for bad in ({'type': 'media'}, {'type': 'media', 'op': 'volume'}):
            page[0]['actions'] = [bad]
            with self.assertRaises(ValueError):
                deck.validate_config(config)
        self.assertIn('media_shuffle', pc_state.FLAG_SOURCES)

    def test_the_daemon_runs_the_action(self):
        daemon = host_support.test_daemon(port='TEST', no_focus=True)
        daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
        with patch.object(deck, 'control_media') as control:
            daemon.run_action({'type': 'media', 'op': 'repeat'})
        control.assert_called_once_with('repeat')


if __name__ == '__main__':
    unittest.main()
