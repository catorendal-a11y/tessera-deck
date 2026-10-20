"""PC state binding: mic/speaker/media flags, label variables and the audio action; no audio hardware."""
import copy
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import pc_state
import tesserad as deck


def audio(volume=40, speaker=False, mic=False):
    return lambda: {'volume': volume, 'speaker_muted': speaker, 'mic_muted': mic}


def media(title='', artist='', status=''):
    return lambda: {'title': title, 'artist': artist, 'status': status}


def failing():
    raise OSError('no device')


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

    def test_unknown_audio_commands_are_rejected(self):
        with self.assertRaises(ValueError):
            pc_state.set_mute('headset', 'toggle')
        with self.assertRaises(ValueError):
            pc_state.set_mute('mic', 'explode')


class DaemonBindingTests(unittest.TestCase):
    def daemon(self, audio_reader=None, media_reader=None):
        daemon = deck.Daemon(types.SimpleNamespace(profiles=str(ROOT / 'host/profiles.default.json'), port='TEST',
                                                   verbose=False, no_focus=True, deck_only=True))
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
        with patch.object(deck, 'set_mute') as mute:
            self.assertTrue(daemon.dispatch_press(8))
        mute.assert_called_once_with('mic', 'toggle')
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


if __name__ == '__main__':
    unittest.main()
