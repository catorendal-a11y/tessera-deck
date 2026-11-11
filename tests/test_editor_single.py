"""One editor window: a second start waits for the first instead of opening a window of its own."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import tessera_app


class RunningEditorTests(unittest.TestCase):
    def record(self, folder, build='b1'):
        path = Path(folder) / 'editor.json'
        path.write_text(json.dumps({'pid': 7, 'created': 100.0, 'url': 'http://127.0.0.1:5000/', 'token': 't', 'build': build}))
        return path

    def running(self):
        process = Mock()
        process.cmdline.return_value = ['python.exe', str(Path(tessera_app.__file__).resolve()), '--editor']
        process.create_time.return_value = 100.0
        answer = MagicMock()
        answer.__enter__.return_value.status = 200
        return process, answer

    def test_a_running_editor_whose_window_is_not_up_yet_is_waited_for(self):
        process, answer = self.running()
        with tempfile.TemporaryDirectory() as folder, patch('psutil.Process', return_value=process), \
                patch.object(tessera_app.urllib.request, 'urlopen', return_value=answer), \
                patch.object(tessera_app, 'open_window') as open_window, \
                patch.object(tessera_app, 'activate_window', return_value=False):
            record = self.record(folder)
            self.assertFalse(tessera_app.show_running_editor(record, 'b1'), 'the caller asks again; it does not open a second window')
            open_window.assert_not_called()
            self.assertTrue(tessera_app.show_running_editor(record, 'b1', open_if_hidden=True))
            open_window.assert_called_once()

    def test_a_visible_editor_is_brought_forward_and_an_older_build_is_stopped(self):
        process, answer = self.running()
        with tempfile.TemporaryDirectory() as folder, patch('psutil.Process', return_value=process), \
                patch.object(tessera_app.urllib.request, 'urlopen', return_value=answer), \
                patch.object(tessera_app, 'open_window') as open_window, \
                patch.object(tessera_app, 'activate_window', return_value=True) as activate:
            self.assertTrue(tessera_app.show_running_editor(self.record(folder), 'b1'))
            activate.assert_called_once_with(7)
            self.assertFalse(tessera_app.show_running_editor(self.record(folder, build='old'), 'b1'))
            process.terminate.assert_called_once()
            open_window.assert_not_called()

    def test_no_record_or_another_program_with_that_pid_is_not_an_editor(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(tessera_app.show_running_editor(Path(folder) / 'missing.json', 'b1'))
            stranger = Mock()
            stranger.cmdline.return_value = ['notepad.exe', 'notes.txt']
            stranger.create_time.return_value = 100.0
            with patch('psutil.Process', return_value=stranger), patch.object(tessera_app.urllib.request, 'urlopen') as urlopen:
                self.assertFalse(tessera_app.show_running_editor(self.record(folder), 'b1'))
                urlopen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
