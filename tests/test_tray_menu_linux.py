"""The right-click menu of the Linux tray icon: what it lists, how clicks are routed, and a real Tk menu on Xvfb."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_marks import linux_only_module
linux_only_module(__name__)
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import types
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
try:
    import pystray
except ImportError:  # the host's venv has it; a bare system Python may not
    pystray = None
from platform_linux import x11_tray_menu as tray_menu


class FakeIcon:
    def __init__(self, calls):
        self.calls = calls

    def __call__(self):  # the default action, as pystray's Icon is called on a left click
        self.calls.append('default')


def fake_icon(calls, has_menu=False):
    def action(name):
        return lambda icon, item=None: calls.append(name)

    def items():
        yield pystray.MenuItem('Status: connected', None, enabled=False)
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem('Open editor', action('open'), default=True)
        yield pystray.MenuItem('Stop host', action('stop'))
        yield pystray.MenuItem('Start with the desktop', action('auto'), checked=lambda item: True)
        yield pystray.MenuItem('Sub', pystray.Menu(pystray.MenuItem('A', action('a')),
                                                   pystray.MenuItem('B', action('b'), checked=lambda item: True, radio=True)))
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem('Quit tray', action('quit'))
        yield pystray.MenuItem('Quit and stop host', action('quit-stop'))
    icon = FakeIcon(calls)
    icon.menu, icon.HAS_MENU, icon._message_handlers = pystray.Menu(items), has_menu, {}
    icon._log = types.SimpleNamespace(error=lambda *a, **k: calls.append('error'))
    return icon


@unittest.skipIf(pystray is None, 'needs pystray')
class DescribeTests(unittest.TestCase):
    def test_the_menu_is_read_as_plain_rows(self):
        rows = tray_menu.describe(fake_icon([]).menu, pystray.Menu.SEPARATOR)
        self.assertEqual([row.get('text', '---') for row in rows],
                         ['Status: connected', '---', 'Open editor', 'Stop host', 'Start with the desktop', 'Sub', '---',
                          'Quit tray', 'Quit and stop host'])
        self.assertFalse(rows[0]['enabled'])
        self.assertTrue(rows[2]['default'])
        self.assertEqual([row['text'] for row in rows[5]['submenu']], ['A', 'B'])

    def test_a_ticked_item_and_a_chosen_radio_item_are_marked(self):
        rows = tray_menu.describe(fake_icon([]).menu, pystray.Menu.SEPARATOR)
        self.assertTrue(tray_menu.label(rows[4]).startswith('✓ '))
        self.assertTrue(tray_menu.label(rows[5]['submenu'][1]).startswith('● '))
        self.assertEqual(tray_menu.label(rows[3]), 'Stop host')


@unittest.skipIf(pystray is None, 'needs pystray')
class ClickTests(unittest.TestCase):
    def test_left_opens_the_default_action_and_right_opens_the_menu(self):
        try:
            import Xlib.X
        except ImportError:
            self.skipTest('needs python-xlib')
        calls, opened = [], []
        icon = fake_icon(calls)
        self.assertTrue(tray_menu.attach(icon, pystray.Menu.SEPARATOR))
        icon.tray_menu.show = lambda x, y: opened.append((x, y))
        handler = icon._message_handlers[Xlib.X.ButtonPress]
        handler(types.SimpleNamespace(detail=1, root_x=5, root_y=6))
        handler(types.SimpleNamespace(detail=3, root_x=40, root_y=50))
        handler(types.SimpleNamespace(detail=2, root_x=1, root_y=1))
        self.assertEqual((calls, opened), (['default'], [(40, 50)]))

    def test_the_x11_tray_gets_its_menu_in_either_session(self):
        # on Plasma Wayland pystray still uses the X11 tray (through XWayland), which has no menu of its own
        from platform_linux import tray
        for session in ('x11', 'wayland'):
            with self.subTest(session=session), unittest.mock.patch('platform_linux.session_type', return_value=session), \
                    unittest.mock.patch.object(tray_menu, 'attach') as attach:
                icon = fake_icon([])
                tray.prepare(icon, pystray.Menu.SEPARATOR)
                self.assertTrue(attach.called)
                self.assertTrue(callable(icon.notify))  # notices go to notify-send in either session

    def test_an_icon_with_a_menu_of_its_own_is_left_alone(self):
        icon = fake_icon([])
        icon.HAS_MENU = True
        self.assertFalse(tray_menu.attach(icon, pystray.Menu.SEPARATOR))

    def test_an_icon_that_has_a_menu_is_left_alone(self):
        self.assertFalse(tray_menu.attach(fake_icon([], has_menu=True), pystray.Menu.SEPARATOR))


@unittest.skipUnless(pystray is not None and sys.platform.startswith('linux')
                     and all(shutil.which(tool) for tool in ('Xvfb', 'xdotool')), 'needs pystray, Xvfb and xdotool')
class RealMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('needs tkinter') from None
        cls.server = subprocess.Popen(['Xvfb', '-displayfd', '1', '-screen', '0', '1024x768x24'], stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True)
        cls.display = ':' + cls.server.stdout.readline().strip()
        cls.saved = os.environ.get('DISPLAY')
        os.environ['DISPLAY'] = cls.display

    @classmethod
    def tearDownClass(cls):
        if cls.saved is None:
            os.environ.pop('DISPLAY', None)
        else:
            os.environ['DISPLAY'] = cls.saved
        cls.server.terminate()
        cls.server.wait(5)

    def test_choosing_an_entry_with_the_keyboard_runs_its_action_and_only_one_menu_opens_at_a_time(self):
        calls = []
        tray = tray_menu.TrayMenu(fake_icon(calls), pystray.Menu.SEPARATOR)
        self.assertTrue(tray.show(200, 200))
        time.sleep(1.0)
        self.assertFalse(tray.show(1, 1))
        subprocess.run(['xdotool', 'key', '--delay', '150', 'Down', 'Down', 'Return'], check=True)  # Open editor, Stop host
        deadline = time.time() + 5
        while 'stop' not in calls and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(calls, ['stop'])
        time.sleep(0.5)
        self.assertTrue(tray._open.acquire(blocking=False))  # the menu closed and can open again


@unittest.skipIf(pystray is None, 'needs pystray')
class PathTests(unittest.TestCase):
    def test_rows_go_to_the_helper_without_the_items_and_a_path_finds_the_item_again(self):
        rows = tray_menu.describe(fake_icon([]).menu, pystray.Menu.SEPARATOR)
        wire = tray_menu.plain(rows)
        self.assertNotIn('item', json.dumps(wire))
        self.assertEqual([row.get('text', '---') for row in wire[5]['submenu']], ['A', 'B'])
        self.assertEqual(str(tray_menu.pick(rows, '3').text), 'Stop host')
        self.assertEqual(str(tray_menu.pick(rows, '5.1').text), 'B')
        for bad in ('', 'x', '99', '5.9', '3.0'):
            self.assertIsNone(tray_menu.pick(rows, bad), bad)

    def test_the_gtk_python_is_found_once_and_never_the_virtual_environment(self):
        saved = list(tray_menu._gtk_python)
        tray_menu._gtk_python.clear()
        self.addCleanup(lambda: (tray_menu._gtk_python.clear(), tray_menu._gtk_python.extend(saved)))
        calls = []

        def run(command, **kwargs):
            calls.append(command[0])
            return types.SimpleNamespace(returncode=0 if command[0] == '/usr/bin/python3' else 1)
        with unittest.mock.patch.object(tray_menu.os.path, 'isfile', return_value=True):
            self.assertEqual(tray_menu.gtk_python(run), '/usr/bin/python3')
            self.assertEqual(tray_menu.gtk_python(run), '/usr/bin/python3')
        self.assertEqual(calls, ['/usr/bin/python3'])  # probed once, then remembered


GTK_PYTHON = tray_menu.gtk_python() if pystray is not None and sys.platform.startswith('linux') else None


@unittest.skipUnless(GTK_PYTHON and shutil.which('Xvfb') and shutil.which('xdotool'), 'needs a Python with GTK, Xvfb and xdotool')
class GtkHelperTests(unittest.TestCase):
    """The helper process in a private X server: what it prints for the keys and clicks a person would use."""
    ROWS = {'x': 300, 'y': 700, 'rows': [
        {'text': 'Status', 'enabled': False, 'checked': None, 'radio': False},
        {'separator': True},
        {'text': 'Open', 'enabled': True, 'checked': None, 'radio': False, 'default': True},
        {'text': 'Stop', 'enabled': True, 'checked': None, 'radio': False},
        {'text': 'Auto', 'enabled': True, 'checked': True, 'radio': False},
        {'text': 'Level', 'enabled': True, 'checked': None, 'radio': False, 'submenu': [
            {'text': '50%', 'enabled': True, 'checked': False, 'radio': True},
            {'text': '100%', 'enabled': True, 'checked': True, 'radio': True}]}]}

    @classmethod
    def setUpClass(cls):
        cls.server = subprocess.Popen(['Xvfb', '-displayfd', '1', '-screen', '0', '1280x800x24'], stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True)
        cls.env = dict(os.environ, DISPLAY=':' + cls.server.stdout.readline().strip())

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(5)

    def choose(self, *keys, click=False):
        helper = subprocess.Popen([GTK_PYTHON, str(tray_menu.HELPER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, env=self.env)
        helper.stdin.write(json.dumps(self.ROWS))
        helper.stdin.close()
        time.sleep(1.5)
        self.assertIsNone(helper.poll(), 'the menu must stay open until someone answers it')
        if click:
            subprocess.run(['xdotool', 'mousemove', '1100', '100', 'click', '1'], env=self.env, check=True)
        else:
            subprocess.run(['xdotool', 'key', '--delay', '150', *keys], env=self.env, check=True)
        out, _ = helper.communicate(timeout=10)
        self.assertEqual(helper.returncode, 0)
        return out.strip()

    def test_the_arrow_keys_skip_the_status_line_and_enter_chooses(self):
        self.assertEqual(self.choose('Down', 'Down', 'Return'), '3')  # Open, Stop
        self.assertEqual(self.choose('Down', 'Down', 'Down', 'Return'), '4')  # a ticked entry

    def test_a_submenu_entry_is_chosen_by_its_path(self):
        self.assertEqual(self.choose('Down', 'Down', 'Down', 'Down', 'Right', 'Down', 'Return'), '5.1')

    def test_escape_and_a_click_elsewhere_close_it_without_a_choice(self):
        self.assertEqual(self.choose('Escape'), '')
        self.assertEqual(self.choose(click=True), '')

    def test_a_click_in_device_pixels_becomes_the_logical_position_of_its_monitor(self):
        """Three scaled monitors as in a real desk setup: the menu must open on the monitor that was clicked."""
        code = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location('helper', sys.argv[1]); helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
class Rect:
    def __init__(self, x, y, w, h): self.x, self.y, self.width, self.height = x, y, w, h
class Monitor:
    def __init__(self, x, y, w, h, scale): self.rect, self.scale = Rect(x, y, w, h), scale
    def get_geometry(self): return self.rect
    def get_scale_factor(self): return self.scale
class Pointer:
    def get_position(self): return (None, 7, 8)
class Seat:
    def get_pointer(self): return Pointer()
class Display:
    monitors = [Monitor(1920, 0, 2560, 1440, 2), Monitor(0, 0, 1920, 1200, 2), Monitor(4480, 0, 1920, 1080, 2)]
    def get_n_monitors(self): return 3
    def get_monitor(self, i): return self.monitors[i]
    def get_default_seat(self): return Seat()
d = Display()
print(helper.to_logical(d, 10204, 1943), helper.to_logical(d, 5000, 2800), helper.to_logical(d, 100, 2300),
      helper.to_logical(d, 99999, 99999))
"""
        done = subprocess.run([GTK_PYTHON, '-c', code, str(tray_menu.HELPER)], capture_output=True, text=True, env=self.env)
        self.assertEqual(done.stdout.strip(), '(5102, 971) (2500, 1400) (50, 1150) (7, 8)', done.stderr)

    def test_building_the_radio_and_check_entries_chooses_nothing_by_itself(self):
        self.assertEqual(self.choose('Escape'), '')  # set_active() inside the helper must not count as a choice


@unittest.skipUnless(pystray is not None and shutil.which('Xvfb') and shutil.which('xdotool'), 'needs pystray, Xvfb, xdotool')
class FallbackTests(unittest.TestCase):
    def test_without_a_python_that_has_gtk_the_tk_menu_still_works(self):
        try:
            import tkinter  # noqa: F401
        except ImportError:
            self.skipTest('needs tkinter')
        server = subprocess.Popen(['Xvfb', '-displayfd', '1', '-screen', '0', '1024x768x24'], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(lambda: (server.terminate(), server.wait(5)))
        display = ':' + server.stdout.readline().strip()
        saved = os.environ.get('DISPLAY')
        os.environ['DISPLAY'] = display
        self.addCleanup(lambda: os.environ.__setitem__('DISPLAY', saved) if saved else os.environ.pop('DISPLAY', None))
        calls = []
        tray = tray_menu.TrayMenu(fake_icon(calls), pystray.Menu.SEPARATOR)
        with unittest.mock.patch.object(tray_menu, 'gtk_python', return_value=None):
            self.assertTrue(tray.show(200, 200))
            time.sleep(1.0)
            subprocess.run(['xdotool', 'key', '--delay', '150', 'Down', 'Down', 'Return'], env=dict(os.environ), check=True)
            deadline = time.time() + 5
            while 'stop' not in calls and time.time() < deadline:
                time.sleep(0.1)
        self.assertEqual(calls, ['stop'])


if __name__ == '__main__':
    unittest.main()
