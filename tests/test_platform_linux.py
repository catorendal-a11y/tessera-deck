"""The Linux desktop backends: session choice, the key vocabulary, the commands they build, and X11 for real."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_marks import linux_only_module
linux_only_module(__name__)
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import platform_linux
from platform_linux import BackendUnavailable
from platform_linux import base, input as linux_input, wayland, x11
import input_common
from platform_windows import input as win_input


class FakeRun:
    def __init__(self, answers=None):
        self.calls, self.answers = [], answers or {}

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        for key, value in self.answers.items():
            if key in args:
                return value
        return ''


class SessionTests(unittest.TestCase):
    def test_the_session_type_picks_the_backend(self):
        self.assertEqual(platform_linux.session_type({'XDG_SESSION_TYPE': 'x11'}), 'x11')
        self.assertEqual(platform_linux.session_type({'XDG_SESSION_TYPE': 'wayland'}), 'wayland')
        self.assertEqual(platform_linux.session_type({'WAYLAND_DISPLAY': 'wayland-0'}), 'wayland')
        self.assertEqual(platform_linux.session_type({'DISPLAY': ':0'}), 'x11')
        self.assertEqual(platform_linux.session_type({}), '')
        self.assertEqual(platform_linux.session_type({'XDG_SESSION_TYPE': 'wayland', 'TESSERA_SESSION': 'x11'}), 'x11')
        self.assertIsInstance(platform_linux.backend({'XDG_SESSION_TYPE': 'x11'}), x11.X11Backend)
        self.assertIsInstance(platform_linux.backend({'XDG_SESSION_TYPE': 'wayland'}), wayland.WaylandBackend)
        self.assertIsInstance(platform_linux.backend({}), base.NoDesktopBackend)

    def test_wayland_and_a_missing_session_refuse_input_with_a_reason(self):
        for env, text in (({'XDG_SESSION_TYPE': 'wayland'}, 'Wayland'), ({}, 'graphical session')):
            backend = platform_linux.backend(env)
            for call in (lambda b=backend: b.send_keys(['ctrl']), lambda b=backend: b.send_text('a'),
                         lambda b=backend: b.send_mouse('left'), lambda b=backend: b.set_clipboard('a')):
                with self.assertRaisesRegex(BackendUnavailable, text):
                    call()
            self.assertIsNone(backend.active_window())

    def test_every_backend_implements_the_whole_interface(self):
        names = [n for n in vars(base.DesktopBackend) if not n.startswith('_') and n != 'name']
        for cls in (x11.X11Backend, wayland.WaylandBackend, base.NoDesktopBackend):
            for name in names:
                self.assertTrue(callable(getattr(cls, name)), (cls, name))


class KeyTests(unittest.TestCase):
    def test_the_key_names_are_exactly_the_windows_virtual_key_table(self):
        self.assertEqual(set(input_common.KEY_NAMES), set(win_input.VK))

    def test_every_host_key_name_has_an_x11_keysym(self):
        missing = sorted(name for name in input_common.KEY_NAMES if name not in x11.KEYSYMS)
        self.assertEqual(missing, [])

    def test_a_hotkey_presses_in_order_and_releases_in_reverse_in_one_call(self):
        fake = FakeRun()
        x11.X11Backend(fake).send_keys(['ctrl', 'shift', 't'])
        self.assertEqual(fake.calls, [['xdotool', 'keydown', 'Control_L', 'keydown', 'Shift_L', 'keydown', 't',
                                       'keyup', 't', 'keyup', 'Shift_L', 'keyup', 'Control_L']])

    def test_an_unknown_key_is_refused_before_anything_is_pressed(self):
        fake = FakeRun()
        with self.assertRaises(ValueError):
            x11.X11Backend(fake).send_keys(['ctrl', 'nonsense'])
        self.assertEqual(fake.calls, [])

    def test_typing_without_a_pause_goes_in_chunks_and_a_stop_request_ends_it(self):
        fake = FakeRun()
        x11.X11Backend(fake).send_text('a' * 150, wait=lambda seconds: False)
        self.assertEqual(len(fake.calls), 3)
        fake = FakeRun()
        x11.X11Backend(fake).send_text('a' * 150, wait=lambda seconds: True)
        self.assertEqual(len(fake.calls), 1)

    def test_typing_with_a_pause_sends_one_character_at_a_time_and_stops_when_asked(self):
        fake, waits = FakeRun(), []
        x11.X11Backend(fake).send_text('abc', 0.2, wait=lambda seconds: waits.append(seconds) or len(waits) == 2)
        self.assertEqual([call[-1] for call in fake.calls], ['a', 'b'])
        self.assertEqual(waits, [0.2, 0.2])

    def test_mouse_operations(self):
        fake = FakeRun()
        backend = x11.X11Backend(fake)
        for args in (('left',), ('right',), ('middle',), ('double',), ('scroll', 0, 0, 3), ('scroll', 0, 0, -2),
                     ('move', 5, -4), ('moveto', 100, 200)):
            backend.send_mouse(*args)
        self.assertEqual(fake.calls, [
            ['xdotool', 'click', '1'], ['xdotool', 'click', '3'], ['xdotool', 'click', '2'],
            ['xdotool', 'click', '--repeat', '2', '--delay', '50', '1'],
            ['xdotool', 'click', '--repeat', '3', '--delay', '10', '4'],
            ['xdotool', 'click', '--repeat', '2', '--delay', '10', '5'],
            ['xdotool', 'mousemove_relative', '--', '5', '-4'], ['xdotool', 'mousemove', '100', '200']])
        with self.assertRaises(ValueError):
            backend.send_mouse('triple')

    def test_every_mouse_operation_of_the_host_is_handled(self):
        for op in input_common.MOUSE_OPERATIONS:
            self.assertIn(op, base.MOUSE_OPERATIONS)
            x11.X11Backend(FakeRun()).send_mouse(op, 1, 1, 1)


class WindowTests(unittest.TestCase):
    def test_the_active_window_is_read_with_its_process_and_title(self):
        fake = FakeRun({'getactivewindow': '4242\n', 'getwindowpid': '777\nMy Title\n'})
        self.assertEqual(x11.X11Backend(fake).active_window(), {'id': '4242', 'pid': 777, 'title': 'My Title'})

    def test_no_active_window_gives_none(self):
        def refuse(args, **kwargs):
            raise OSError('xdotool failed')
        self.assertIsNone(x11.X11Backend(refuse).active_window())

    def test_maximize_and_restore_change_each_property_in_its_own_call(self):
        fake = FakeRun()
        backend = x11.X11Backend(fake)
        backend.window_op('9', 'maximize')
        backend.window_op('9', 'restore')
        self.assertEqual([c for c in fake.calls if c[1] == 'windowstate'], [
            ['xdotool', 'windowstate', '--add', 'MAXIMIZED_VERT', '9'], ['xdotool', 'windowstate', '--add', 'MAXIMIZED_HORZ', '9'],
            ['xdotool', 'windowstate', '--remove', 'MAXIMIZED_VERT', '9'], ['xdotool', 'windowstate', '--remove', 'MAXIMIZED_HORZ', '9']])

    def test_topmost_turns_the_state_on_or_off_by_what_it_finds(self):
        on = FakeRun({'xprop': '_NET_WM_STATE(ATOM) = _NET_WM_STATE_ABOVE, _NET_WM_STATE_FOCUSED'})
        x11.X11Backend(on).window_op('9', 'topmost')
        self.assertIn(['xdotool', 'windowstate', '--remove', 'ABOVE', '9'], on.calls)
        off = FakeRun({'xprop': '_NET_WM_STATE(ATOM) = _NET_WM_STATE_FOCUSED'})
        x11.X11Backend(off).window_op('9', 'topmost')
        self.assertIn(['xdotool', 'windowstate', '--add', 'ABOVE', '9'], off.calls)

    def test_every_window_operation_of_the_host_is_handled(self):
        for op in input_common.WINDOW_OPERATIONS:
            fake = FakeRun({'xrandr': 'Monitors: 1\n 0: +*A 100/1x100/1+0+0 A', 'getwindowgeometry': 'X=0 Y=0 WIDTH=1 HEIGHT=1',
                            'getactivewindow': '5'})
            self.assertTrue(x11.X11Backend(fake).window_op('9', op), op)

    def test_a_missing_tool_names_the_package_to_install(self):
        with unittest.mock.patch.object(shutil, 'which', return_value=None):
            with self.assertRaisesRegex(BackendUnavailable, 'install the "xdotool" package'):
                x11.run(['xdotool', 'version'])


class MatchingTests(unittest.TestCase):
    def test_a_windows_style_name_matches_the_linux_program(self):
        context = {'exe': 'firefox', 'title': 'docs - mozilla firefox', 'processes': ['firefox', 'bash']}
        for pattern in ('firefox', 'firefox.exe', 'FIREFOX.EXE', 'process:bash', 'title:mozilla'):
            self.assertTrue(linux_input.matches_foreground(pattern, context), pattern)
        self.assertFalse(linux_input.matches_foreground('chrome.exe', context))

    def test_desktop_shells_and_tessera_itself_are_neutral(self):
        self.assertTrue(linux_input.is_neutral_window({'exe': 'cinnamon', 'title': ''}))
        self.assertTrue(linux_input.is_neutral_window({'exe': 'python3.14', 'title': 'tessera editor'}))
        self.assertFalse(linux_input.is_neutral_window({'exe': 'firefox', 'title': 'tessera'}))

    def test_the_host_gets_the_linux_functions_from_desktop_on_linux_and_the_windows_ones_stay_separate(self):
        if not sys.platform.startswith('linux'):
            self.skipTest('Linux only')
        import desktop
        self.assertIs(desktop.send_hotkey, linux_input.send_hotkey)
        self.assertIs(desktop.window_action, linux_input.window_action)
        self.assertIsNot(win_input.send_hotkey, linux_input.send_hotkey)


@unittest.skipUnless(sys.platform.startswith('linux') and all(shutil.which(tool) for tool in ('Xvfb', 'xdotool', 'xterm', 'xclip')),
                     'needs Xvfb, xdotool, xterm and xclip')
class X11IntegrationTests(unittest.TestCase):
    """Keys, text, clicks and the clipboard against a private X server: nothing touches the real desktop."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        # -displayfd lets Xvfb pick a free display number, so a second test run (or a real X server) never collides
        cls.server = subprocess.Popen(['Xvfb', '-displayfd', '1', '-screen', '0', '1280x800x24'], stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True)
        cls.display = ':' + cls.server.stdout.readline().strip()
        cls.env = dict(os.environ, DISPLAY=cls.display)
        cls.typed = Path(cls.folder, 'typed.txt')
        cls.term = subprocess.Popen(['xterm', '-title', 'tessera-test', '-e', f'stty raw -echo; cat > {cls.typed}'], env=cls.env,
                                    stderr=subprocess.DEVNULL)
        time.sleep(1.5)
        window = subprocess.run(['xdotool', 'search', '--pid', str(cls.term.pid)], env=cls.env, capture_output=True, text=True).stdout.split()[0]
        subprocess.run(['xdotool', 'windowfocus', window], env=cls.env, check=True)
        cls.backend = x11.X11Backend(cls.run_in_display)

    @classmethod
    def run_in_display(cls, args, stdin=None, timeout=x11.TIMEOUT, detach=False):
        saved = os.environ.get('DISPLAY')
        os.environ['DISPLAY'] = cls.display
        try:
            return x11.run(args, stdin=stdin, timeout=timeout, detach=detach)
        finally:
            if saved is None:
                os.environ.pop('DISPLAY', None)
            else:
                os.environ['DISPLAY'] = saved

    @classmethod
    def tearDownClass(cls):
        for process in (cls.term, cls.server):
            process.terminate()
            process.wait(5)
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_text_keys_and_the_clipboard_reach_the_focused_program(self):
        self.backend.send_text('Héllo € ✓\nnext\tx')
        self.backend.send_keys(['ctrl', 'shift', 'a'])
        self.backend.send_keys(['f5'])
        self.backend.set_clipboard('from the clipboard ✓')
        self.backend.send_keys(['ctrl', 'v'])
        time.sleep(0.5)
        self.assertEqual(subprocess.run(['xclip', '-selection', 'clipboard', '-o'], env=self.env, capture_output=True, text=True).stdout,
                         'from the clipboard ✓')
        data = self.typed.read_bytes().decode('utf-8', 'replace')
        self.assertTrue(data.startswith('Héllo € ✓\nnext\tx'), data)
        self.assertIn('\x01', data)  # ctrl+shift+a
        self.assertIn('\x1b[15~', data)  # F5

    def test_the_mouse_moves_and_the_window_of_a_program_is_found(self):
        self.backend.send_mouse('moveto', 300, 200)
        self.backend.send_mouse('move', 10, 5)
        where = subprocess.run(['xdotool', 'getmouselocation'], env=self.env, capture_output=True, text=True).stdout
        self.assertTrue(where.startswith('x:310 y:205'), where)
        self.assertIsNotNone(self.backend.find_window({self.term.pid}))


if __name__ == '__main__':
    unittest.main()
