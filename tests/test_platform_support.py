"""The platform selector, and that the Windows package offers every function and constant the shared code uses."""
import importlib
from pathlib import Path
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
    'session': ['locked'],
    'secrets': ['seal', 'unseal'],
    'shortcuts': ['desktop_shortcut_path', 'create_shortcut'],
    'dialogs': ['ask_yes_no'],
    'tray': ['prepare'],
    'filelock': ['lock', 'unlock'],
    'autostart': ['startup_script_path', 'is_enabled', 'enable'],
    'shell': ['scan_programs', 'shortcut_target'],
    'editor_window': ['activate_window', 'brand_taskbar_identity', 'open_native_window'],
    'programs': ['describe', 'script_command', 'locate'],
    'processes': ['kill_tree', 'spawn_options', 'open_path', 'open_target', 'edit_script', 'notification_beep'],
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
                               'PLUGIN_ENV_KEEP', 'VENV_SCRIPTS', 'VENV_PYTHON', 'VENV_PYTHON_WINDOWLESS']}


class SelectorTests(unittest.TestCase):
    def test_the_system_name_maps_to_the_platform(self):
        self.assertEqual(platform_support.detect('win32'), 'windows')

    def test_detect_refuses_other_systems_with_their_name(self):
        for name in ('linux', 'darwin', 'freebsd14', 'cygwin', 'aix'):
            with self.assertRaisesRegex(platform_support.UnsupportedPlatform, name):
                platform_support.detect(name)

    def test_load_gives_the_module_of_the_windows_package(self):
        self.assertEqual(platform_support.NAME, 'windows')
        self.assertEqual(platform_support.load('autostart').__name__, 'platform_windows.autostart')

    def test_the_host_modules_import_on_a_development_machine_that_is_not_windows(self):
        """The build tools and the benchmark of the image cache import host modules on Linux; that has to keep working."""
        code = "import sys; sys.path.insert(0, 'host'); import desktop, system_audio, firmware_update, panel_serial"
        result = subprocess.run([sys.executable, '-I', '-c', code], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-400:])


class WindowsPackageTests(unittest.TestCase):
    """The shared code calls these names on whatever system it runs on: the package of the system has all of them."""

    def test_the_package_offers_every_shared_function_and_constant(self):
        for module, names in SHARED_FUNCTIONS.items():
            package = importlib.import_module(f'platform_windows.{module}')
            for name in names:
                with self.subTest(module=module, name=name):
                    self.assertTrue(hasattr(package, name), f'platform_windows.{module}.{name} is missing')
        for module, names in SHARED_CONSTANTS.items():
            package = importlib.import_module(f'platform_windows.{module}')
            for name in names:
                with self.subTest(module=module, name=name):
                    self.assertTrue(hasattr(package, name), f'platform_windows.{module}.{name} is missing')

    def test_the_desktop_facade_exports_every_shared_input_name(self):
        import desktop
        for name in SHARED_FUNCTIONS['input']:
            self.assertTrue(hasattr(desktop, name), name)


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
# libraries that exist on Windows only
WINDOWS_ONLY = 'msvcrt,winreg,winsound,_winapi,win32pdh,win32api,win32con,win32gui,pycaw,comtypes,winrt'


class ImportableEverywhereTests(unittest.TestCase):
    """Every module of the package imports on any system: a system library is imported where it is used, so the shared
    tests can import the package on a development machine that is not Windows."""

    @unittest.skipIf(platform_support.IS_WINDOWS, 'subprocess and others need these libraries on Windows; here they are missing for real')
    def test_the_windows_modules_import_without_the_windows_libraries(self):
        names = sorted(f'platform_windows.{path.stem}' for path in (ROOT / 'host/platform_windows').glob('*.py'))
        result = subprocess.run([sys.executable, '-I', '-c', PORTABLE_PROBE, WINDOWS_ONLY, *names], cwd=ROOT,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        import json
        self.assertEqual(json.loads(result.stdout.splitlines()[-1]), {})


if __name__ == '__main__':
    unittest.main()
