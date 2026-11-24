"""The platform selector, and that the Windows and Linux packages offer the same functions to the shared code."""
import importlib
import inspect
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import platform_support  # noqa: E402

# module -> the names the shared code calls on both systems
SHARED_FUNCTIONS = {
    'audio': ['control_audio', 'read_audio', 'read_mixer'],
    'media': ['MediaReader', 'control_media'],
    'session': ['locked', 'idle_seconds'],
    'secrets': ['seal', 'unseal'],
    'shortcuts': ['desktop_shortcut_path', 'shortcut_files', 'create_shortcut'],
    'dialogs': ['ask_yes_no', 'tell'],
    'tray': ['prepare', 'choose_backend'],
    'remote': ['list_devices', 'read_device', 'write_volume', 'send_action'],
    'filelock': ['lock', 'unlock'],
    'autostart': ['startup_script_path', 'is_enabled', 'enable'],
    'shell': ['scan_programs', 'shortcut_target'],
    'editor_window': ['activate_window', 'brand_taskbar_identity', 'open_native_window'],
    'programs': ['describe', 'script_command', 'locate'],
    'processes': ['kill_tree', 'name_process', 'spawn_options', 'open_path', 'open_target', 'edit_script', 'notification_beep'],
    'files': ['make_private'],
    'sensors': ['native_counters', 'hwinfo_reader', 'disk_root', 'extra_gpu_readers'],
    'icons': ['program_icon_image'],
    'regional': ['clock_format'],
    'input': ['bring_to_front', 'focus_existing_process', 'foreground_context', 'is_neutral_window', 'matches_foreground',
              'process_window', 'send_hotkey', 'send_mouse', 'send_text', 'set_clipboard', 'window_action'],
}
# module -> the constants the shared code reads on both systems
SHARED_CONSTANTS = {'processes': ['STOP_BY_KILLING_TREE'],
                    'sensors': ['NATIVE_SENSORS'],
                    'process_flags': ['NO_WINDOW', 'NEW_PROCESS_GROUP', 'DETACHED', 'NEW_CONSOLE'],
                    'labels': ['MODULE_PROBE', 'AUTOSTART_NAME', 'SHORTCUT_NAME', 'LAUNCHER', 'ASKS_ABOUT_AUTOSTART', 'PROGRAM_SUFFIX',
                               'PROGRAM_EXAMPLE', 'PROGRAM_LIST_NOTE', 'SCRIPT_EXTRA_SUFFIXES', 'DEFAULT_PROFILE', 'DEFAULT_PORT',
                               'RESETS_ON_OPEN', 'PLUGIN_ENV_KEEP', 'VENV_SCRIPTS', 'VENV_PYTHON', 'VENV_PYTHON_WINDOWLESS']}
FCNTL = re.compile(r'^\s*(?:import fcntl|from fcntl\b)', re.MULTILINE)


class SelectorTests(unittest.TestCase):
    def test_the_system_names_map_to_one_platform(self):
        self.assertEqual(platform_support.detect('win32'), 'windows')
        self.assertEqual(platform_support.detect('linux'), 'linux')
        self.assertEqual(platform_support.detect('linux2'), 'linux')

    def test_other_systems_are_refused_with_their_name(self):
        for name in ('darwin', 'freebsd14', 'cygwin', 'aix'):
            with self.assertRaisesRegex(platform_support.UnsupportedPlatform, name):
                platform_support.detect(name)

    def test_load_gives_the_module_of_this_system(self):
        self.assertEqual(platform_support.load('autostart').__name__, f'platform_{platform_support.NAME}.autostart')

    def test_this_system_has_exactly_one_flag(self):
        self.assertNotEqual(platform_support.IS_WINDOWS, platform_support.IS_LINUX)
        self.assertEqual(platform_support.NAME, 'windows' if platform_support.IS_WINDOWS else 'linux')

    def test_the_host_does_not_start_on_macos(self):
        code = ("import sys; sys.platform = 'darwin'; sys.path.insert(0, 'host'); import desktop")
        result = subprocess.run([sys.executable, '-I', '-c', code], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('UnsupportedPlatform', result.stderr)
        self.assertIn("not on 'darwin'", result.stderr)


class ParityTests(unittest.TestCase):
    """Both packages are imported on every system, so a change on one side that the other lacks fails on either."""

    def test_both_packages_offer_the_same_names_with_the_same_required_parameters(self):
        """The shared code passes the required parameters positionally. A side may add optional parameters (the Linux
        functions take `run`, `now` and `reader` so tests can replace a command) and may name them differently."""
        for module, names in SHARED_FUNCTIONS.items():
            windows = importlib.import_module(f'platform_windows.{module}')
            linux = importlib.import_module(f'platform_linux.{module}')
            for name in names:
                with self.subTest(module=module, name=name):
                    self.assertTrue(hasattr(windows, name), f'platform_windows.{module}.{name} is missing')
                    self.assertTrue(hasattr(linux, name), f'platform_linux.{module}.{name} is missing')
                    self.assertEqual(self.required(getattr(windows, name)), self.required(getattr(linux, name)))

    @staticmethod
    def required(item):
        """How many parameters have no default; for a class, those of its __init__."""
        target = item.__init__ if inspect.isclass(item) else item
        return sum(1 for p in inspect.signature(target).parameters.values()
                   if p.name != 'self' and p.default is p.empty and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD))

    def test_both_packages_have_the_same_constants_of_the_same_type(self):
        for module, names in SHARED_CONSTANTS.items():
            windows = importlib.import_module(f'platform_windows.{module}')
            linux = importlib.import_module(f'platform_linux.{module}')
            for name in names:
                with self.subTest(module=module, name=name):
                    self.assertIsInstance(getattr(linux, name), type(getattr(windows, name)))

    def test_the_desktop_facade_exports_every_shared_input_name(self):
        import desktop
        for name in SHARED_FUNCTIONS['input']:
            self.assertTrue(hasattr(desktop, name), name)


ISOLATION_PROBE = """
import importlib, json, sys
other = sys.argv[1]
sys.modules[other] = None  # any import of the other system's package now raises ImportError
sys.path.insert(0, 'host')
found = {}
for name in sys.argv[2:]:
    try:
        importlib.import_module(name)
    except ImportError as exc:
        if other in str(exc):
            found[name] = str(exc)
    except Exception:
        pass  # a missing optional library or a display is not what this checks
print(json.dumps(found))
"""
# modules that start work or a window when imported
NOT_IMPORTED = {'start_host', 'deckctl', 'tessera_terminal', 'editor_file_picker'}


class IsolationTests(unittest.TestCase):
    def test_no_shared_module_imports_the_other_systems_package(self):
        """A Linux start never imports platform_windows and a Windows start never imports platform_linux."""
        other = 'platform_linux' if platform_support.IS_WINDOWS else 'platform_windows'
        names = sorted(path.stem for path in (ROOT / 'host').glob('*.py') if path.stem not in NOT_IMPORTED)
        result = subprocess.run([sys.executable, '-I', '-c', ISOLATION_PROBE, other, *names], cwd=ROOT,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        import json
        self.assertEqual(json.loads(result.stdout.splitlines()[-1]), {})


PORTABLE_PROBE = """
import importlib, json, sys
for name in sys.argv[1:2][0].split(','):
    sys.modules[name] = None  # the system library is missing, as on the other system
sys.path.insert(0, 'host')
failed = {}
for name in sys.argv[2:]:
    try:
        importlib.import_module(name)
    except Exception as exc:
        failed[name] = f'{type(exc).__name__}: {exc}'
print(json.dumps(failed))
"""
# libraries that exist on one system only
POSIX_ONLY = 'fcntl,termios'  # the ones this project could import; psutil and others bring their own system libraries
WINDOWS_ONLY = 'msvcrt,winreg,winsound,_winapi,win32pdh,win32api,win32con,win32gui,pycaw,comtypes,winrt'


# programs that run in their own process (the tray menu and editor window helpers exit when their GTK libraries are missing)
SCRIPTS = {'x11_menu_helper', 'editor_window_helper'}


class ImportableEverywhereTests(unittest.TestCase):
    """Every module of both packages imports on any system: a system library is imported where it is used. The parity
    test imports both packages on both systems, so a module that cannot would fail the other system's tests."""

    def check(self, package, missing):
        names = sorted(f'{package}.{path.stem}' for path in (ROOT / 'host' / package).glob('*.py')
                       if path.stem not in SCRIPTS)
        result = subprocess.run([sys.executable, '-I', '-c', PORTABLE_PROBE, missing, *names], cwd=ROOT,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        import json
        self.assertEqual(json.loads(result.stdout.splitlines()[-1]), {})

    def test_the_linux_modules_import_without_the_posix_libraries(self):
        self.check('platform_linux', POSIX_ONLY)

    @unittest.skipIf(platform_support.IS_WINDOWS, 'subprocess and others need these libraries on Windows; here they are missing for real')
    def test_the_windows_modules_import_without_the_windows_libraries(self):
        self.check('platform_windows', WINDOWS_ONLY)


class LayeringTests(unittest.TestCase):
    def test_shared_modules_do_not_import_fcntl(self):
        offenders = [path.name for path in sorted((ROOT / 'host').glob('*.py'))
                     if FCNTL.search(path.read_text(encoding='utf-8'))]
        self.assertEqual(offenders, [], 'the Linux file lock is platform_linux/filelock.py')

    def test_the_linux_package_imports_nothing_from_the_windows_package(self):
        offenders = [path.name for path in sorted((ROOT / 'host/platform_linux').glob('*.py'))
                     if 'platform_windows' in re.sub(r'#.*|""".*?"""', '', path.read_text(encoding='utf-8'), flags=re.S)]
        self.assertEqual(offenders, [])

    def test_the_windows_package_imports_nothing_from_the_linux_package(self):
        offenders = [path.name for path in sorted((ROOT / 'host/platform_windows').glob('*.py'))
                     if 'platform_linux' in re.sub(r'#.*|""".*?"""', '', path.read_text(encoding='utf-8'), flags=re.S)]
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
