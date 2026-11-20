"""The editor's own window on Linux: when it opens, what it is told, and when the browser takes over."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_marks import linux_only_module
linux_only_module(__name__)
import json
import os
import subprocess
import types
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from platform_linux import editor_window


def answers(*done):
    """A fake subprocess.run that gives these results in turn and keeps what it was asked."""
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return done[len(calls) - 1]
    return run, calls


def result(code=0, out=''):
    return types.SimpleNamespace(returncode=code, stdout=out, stderr='')


class OpenTests(unittest.TestCase):
    def open(self, run, saved):
        with unittest.mock.patch.object(editor_window, 'gtk_python', return_value='/usr/bin/python3'), \
                unittest.mock.patch.object(subprocess, 'run', run), unittest.mock.patch.dict(os.environ, {'TESSERA_EDITOR': ''}):
            return editor_window.open_native_window('http://127.0.0.1:1/', lambda screen: (900, 700, None, None),
                                                    saved.append, (1050, 640), ROOT)

    def test_the_window_gets_the_size_for_the_screen_and_its_last_size_is_saved(self):
        run, calls = answers(result(out=json.dumps({'x': 0, 'y': 0, 'width': 1920, 'height': 1050})),
                             result(out=json.dumps({'width': 1200, 'height': 800, 'x': 10, 'y': 20})))
        saved = []
        self.assertTrue(self.open(run, saved))
        self.assertEqual(calls[0][0][-1], '--screen')
        request = json.loads(calls[1][1]['input'])
        self.assertEqual((request['url'], request['width'], request['height'], request['x']), ('http://127.0.0.1:1/', 900, 700, None))
        self.assertEqual(saved, [{'width': 1200, 'height': 800, 'x': 10, 'y': 20}])

    def test_without_webkitgtk_the_browser_opens(self):
        run, calls = answers(result(editor_window.NO_GTK))
        self.assertFalse(self.open(run, []))
        self.assertEqual(len(calls), 1)

    def test_without_a_gtk_python_or_when_asked_for_the_browser_no_window_is_tried(self):
        with unittest.mock.patch.object(editor_window, 'gtk_python', return_value=None):
            self.assertFalse(editor_window.open_native_window('u', None, None, (1, 1), ROOT))
        with unittest.mock.patch.dict(os.environ, {'TESSERA_EDITOR': 'browser'}), \
                unittest.mock.patch.object(editor_window, 'gtk_python') as find:
            self.assertFalse(editor_window.open_native_window('u', None, None, (1, 1), ROOT))
            find.assert_not_called()


class RendererTests(unittest.TestCase):
    def test_the_dmabuf_renderer_is_off_unless_the_user_chose(self):
        import platform_linux.editor_window_helper as helper
        for preset, expected in ((None, '1'), ('0', '0')):
            env = {} if preset is None else {'WEBKIT_DISABLE_DMABUF_RENDERER': preset}
            with unittest.mock.patch.dict(os.environ, env, clear=True), unittest.mock.patch.dict(sys.modules, {'gi': None}):
                self.assertIsNone(helper.load())
                self.assertEqual(os.environ['WEBKIT_DISABLE_DMABUF_RENDERER'], expected)


class ActivateTests(unittest.TestCase):
    def test_the_window_of_the_helper_child_is_brought_to_the_front(self):
        backend = unittest.mock.Mock()
        backend.find_window.return_value = '{w}'
        backend.window_op.return_value = True
        helper = unittest.mock.Mock(pid=4321, **{'cmdline.return_value': ['/usr/bin/python3', str(editor_window.HELPER)]})
        other = unittest.mock.Mock(pid=99, **{'cmdline.return_value': ['bash']})
        editor = unittest.mock.Mock(**{'children.return_value': [helper, other]})
        with unittest.mock.patch('platform_linux.backend', return_value=backend), \
                unittest.mock.patch.object(editor_window.psutil, 'Process', return_value=editor):
            self.assertTrue(editor_window.activate_window(1234))
        backend.find_window.assert_called_with({4321})
        backend.window_op.assert_called_with('{w}', 'focus')

    def test_an_editor_without_the_window_helper_is_not_raised(self):
        backend = unittest.mock.Mock()
        with unittest.mock.patch('platform_linux.backend', return_value=backend):
            self.assertFalse(editor_window.activate_window(os.getpid()))
        backend.find_window.assert_not_called()

    def test_a_gone_editor_is_not_found(self):
        self.assertFalse(editor_window.activate_window(2 ** 22 + 12345))


if __name__ == '__main__':
    unittest.main()
