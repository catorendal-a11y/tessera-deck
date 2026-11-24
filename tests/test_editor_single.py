"""One editor window: a second start waits for the first instead of opening a window of its own."""
import contextlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import itertools
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, Mock, patch
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import deckctl
import tessera_app
from control_api import proof
from host_runtime import InstanceLock


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
        answer.__enter__.return_value.read.return_value = b'{"ok": true, "launch": "one-time"}'
        return process, answer

    def test_a_running_editor_whose_window_is_not_up_yet_is_waited_for(self):
        process, answer = self.running()
        with tempfile.TemporaryDirectory() as folder, patch('psutil.Process', return_value=process), \
                patch.object(tessera_app.LOCAL, 'open', return_value=answer), \
                patch.object(tessera_app, 'open_window') as open_window, \
                patch.object(tessera_app, 'activate_window', return_value=False):
            record = self.record(folder)
            self.assertFalse(tessera_app.show_running_editor(record, 'b1'), 'the caller asks again; it does not open a second window')
            open_window.assert_not_called()
            self.assertTrue(tessera_app.show_running_editor(record, 'b1', open_if_hidden=True))
            # the address carries a one-time code from the editor, never the record's long-lived token
            open_window.assert_called_once()
            self.assertEqual(open_window.call_args.args[0](), 'http://127.0.0.1:5000/#one-time')

    def test_the_browser_gets_a_launch_code_of_its_own_when_the_window_fails(self):
        # a window that loaded the page and then failed has used its one-time code
        codes = iter(['http://127.0.0.1:5000/#first', 'http://127.0.0.1:5000/#second'])
        window = Mock(**{'open_native_window.return_value': False})
        with patch.object(tessera_app, 'load', return_value=window), patch.object(tessera_app.webbrowser, 'open') as browser:
            self.assertFalse(tessera_app.open_window(lambda: next(codes)))
        self.assertEqual(window.open_native_window.call_args.args[0], 'http://127.0.0.1:5000/#first')
        browser.assert_called_once_with('http://127.0.0.1:5000/#second')

    def test_a_visible_editor_is_brought_forward_and_an_older_build_is_stopped(self):
        process, answer = self.running()
        with tempfile.TemporaryDirectory() as folder, patch('psutil.Process', return_value=process), \
                patch.object(tessera_app.LOCAL, 'open', return_value=answer), \
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
            with patch('psutil.Process', return_value=stranger), patch.object(tessera_app.LOCAL, 'open') as urlopen:
                self.assertFalse(tessera_app.show_running_editor(self.record(folder), 'b1'))
                urlopen.assert_not_called()


class SecondStartTests(unittest.TestCase):
    def test_a_second_start_that_gets_no_answer_says_so_before_it_gives_up(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'host').mkdir()
            running = InstanceLock(Path(folder) / 'host/editor.local.lock')  # the first editor holds the lock
            self.assertTrue(running.acquire())
            stderr = io.StringIO()
            try:
                with patch.object(sys, 'argv', ['tessera_app.py', '--editor']), patch.object(tessera_app, 'ROOT', Path(folder)), \
                        patch.object(tessera_app, 'load'), patch.object(tessera_app, 'Controller'), \
                        patch.object(tessera_app, 'editor_build_id', return_value='b1'), \
                        patch.object(tessera_app, 'show_running_editor', return_value=False) as show, \
                        patch.object(tessera_app.time, 'monotonic', side_effect=itertools.count(0, 5)), \
                        patch.object(tessera_app.time, 'sleep'), contextlib.redirect_stderr(stderr):
                    tessera_app.main()
            finally:
                running.release()
        show.assert_called()
        self.assertIn('did not answer', stderr.getvalue())


class LocalServer(BaseHTTPRequestHandler):
    """A stand-in for the editor's and the host's own server on this PC."""
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length') or 0))
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header('X-Deck-Proof', proof('t', self.headers['X-Deck-Nonce'] or ''))
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST

    def log_message(self, *args):
        pass


class ProxyTests(unittest.TestCase):
    """A proxy from HTTP_PROXY or the Windows settings must not take the calls to this PC's own servers."""
    def setUp(self):
        server = HTTPServer(('127.0.0.1', 0), LocalServer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_port
        with socket.socket() as spare:  # a port nothing listens on: the company proxy that cannot be reached
            spare.bind(('127.0.0.1', 0))
            dead = spare.getsockname()[1]
        environment = {name: f'http://127.0.0.1:{dead}' for name in ('HTTP_PROXY', 'http_proxy')}
        patcher = patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ('NO_PROXY', 'no_proxy'):
            os.environ.pop(name, None)
        # urlopen keeps the first opener it builds, with the proxies of that moment; an earlier test may have built it
        opener = patch.object(urllib.request, '_opener', None)
        opener.start()
        self.addCleanup(opener.stop)

    def test_the_second_start_reaches_the_running_editor_through_a_proxy(self):
        process = Mock()
        process.cmdline.return_value = ['python.exe', str(Path(tessera_app.__file__).resolve()), '--editor']
        process.create_time.return_value = 100.0
        with tempfile.TemporaryDirectory() as folder:
            record = Path(folder) / 'editor.json'
            record.write_text(json.dumps({'pid': 7, 'created': 100.0, 'url': f'http://127.0.0.1:{self.port}/',
                                          'token': 't', 'build': 'b1'}))
            with patch('psutil.Process', return_value=process), patch.object(tessera_app, 'activate_window', return_value=True):
                self.assertTrue(tessera_app.show_running_editor(record, 'b1'))

    def test_deckctl_reaches_the_host_through_a_proxy(self):
        self.assertEqual(deckctl.call({'port': self.port, 'token': 't'}, 'POST', '/api/x', {}), {'ok': True})


class WindowSizeTests(unittest.TestCase):
    laptop = Mock(x=0, y=0, width=1366, height=768)

    def test_a_first_start_fits_a_small_laptop_screen(self):
        width, height, x, y = tessera_app.window_geometry(self.laptop, Path('missing.local.json'))
        self.assertLessEqual((width, height), (1366, 768))
        self.assertGreaterEqual(height, 640)
        self.assertEqual((x, y), (None, None))

    def test_the_last_size_comes_back_but_stays_on_the_screen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'window.local.json'
            tessera_app.save_window_geometry({'width': 1200, 'height': 700, 'x': 40, 'y': 30}, path)
            self.assertEqual(tessera_app.window_geometry(self.laptop, path), (1200, 700, 40, 30))
            tessera_app.save_window_geometry({'width': 1900, 'height': 160, 'x': -32000, 'y': -32000}, path)
            self.assertEqual(tessera_app.window_geometry(self.laptop, path), (1366, 640, 0, 0))
            tessera_app.save_window_geometry({'width': 1200}, path)  # incomplete: the earlier size is kept
            self.assertEqual(tessera_app.window_geometry(self.laptop, path), (1366, 640, 0, 0))


if __name__ == '__main__':
    unittest.main()
