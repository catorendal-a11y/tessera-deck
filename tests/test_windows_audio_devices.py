"""A program playing on another output device than the default one still has its volume found and controlled."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))


@unittest.skipUnless(sys.platform == 'win32', 'pycaw is Windows only')
class OtherDeviceTests(unittest.TestCase):
    """Fakes stand in for Core Audio only: one enumerator, two output devices, the program on the second."""

    def setUp(self):
        from pycaw.api.audioclient import ISimpleAudioVolume
        from pycaw.api.audiopolicy import IAudioSessionControl2
        self.program = psutil.Process(os.getpid()).name()
        self.volume = Mock(**{'GetMute.return_value': 0, 'GetMasterVolume.return_value': 0.4})
        control2 = Mock(**{'GetProcessId.return_value': os.getpid(), 'GetState.return_value': 1})
        control2.QueryInterface.side_effect = lambda iface: self.volume if iface is ISimpleAudioVolume else None
        control = Mock()
        control.QueryInterface.side_effect = lambda iface: control2 if iface is IAudioSessionControl2 else None
        session_list = Mock(**{'GetCount.return_value': 1, 'GetSession.return_value': control})
        busy = Mock()
        busy.QueryInterface.side_effect = lambda iface: Mock(**{'GetSessionEnumerator.return_value': session_list})
        quiet = Mock()
        quiet.QueryInterface.side_effect = lambda iface: Mock(**{'GetSessionEnumerator.return_value': Mock(**{'GetCount.return_value': 0})})
        speakers, headset = Mock(), Mock()
        speakers.Activate.return_value, headset.Activate.return_value = quiet, busy
        devices = [speakers, headset]
        collection = Mock(**{'GetCount.return_value': 2})
        collection.Item.side_effect = lambda i: devices[i]
        self.enumerator = Mock(**{'EnumAudioEndpoints.return_value': collection})

    def test_a_program_on_the_headset_is_found_while_the_speakers_are_default(self):
        from platform_windows import audio
        with patch('pycaw.pycaw.AudioUtilities.GetDeviceEnumerator', return_value=self.enumerator):
            controls = audio._app_controls(self.program)
        self.assertEqual(len(controls), 1)
        self.assertEqual(controls[0].get_volume(), 0.4)

    def test_the_mixer_lists_a_program_on_the_headset(self):
        from platform_windows import audio
        speaker = Mock(**{'GetMasterVolumeLevelScalar.return_value': 0.5, 'GetMute.return_value': False})
        with patch('platform_windows.audio._with_audio', side_effect=lambda work: work({'speaker': speaker, 'mic': None})), \
                patch('pycaw.pycaw.AudioUtilities.GetDeviceEnumerator', return_value=self.enumerator):
            ids = [fader['id'] for fader in audio.read_mixer()]
        self.assertEqual(ids, ['speaker', 'app:' + self.program])


if __name__ == '__main__':
    unittest.main()
