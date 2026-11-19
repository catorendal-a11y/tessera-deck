"""The Windows-specific package: every module can be imported on any system (they only call Windows APIs when used),
exposes what the rest of the host expects, and shared code names no Windows API outside it."""
import importlib
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))

# module -> names the rest of the host imports from it
EXPECTED = {
    'platform_windows.input': ['VK', 'parse_hotkey', 'send_hotkey', 'send_text', 'send_mouse', 'set_clipboard', 'window_action',
                               'foreground_context', 'focus_existing_process', 'process_window', 'bring_to_front',
                               'is_neutral_window', 'real_app_exe', 'matches_foreground', '_key'],
    'platform_windows.audio': ['read_audio', 'control_audio', 'read_mixer', '_with_audio', '_app_controls', 'apply_operation'],
    'platform_windows.media': ['MediaReader', 'control_media', '_change_media_option'],
    'platform_windows.secrets': ['dpapi', 'seal', 'unseal'],
    'platform_windows.sensors': ['WindowsCounters', 'LibreHardwareMonitorReader', 'flatten_sensor_tree', 'native_counters', 'hwinfo_reader',
                                 'disk_root', 'extra_gpu_readers', 'NATIVE_SENSORS'],
    'platform_windows.hwinfo': ['HWiNFOReader'],
    'platform_windows.gpu_adl': ['AdlReader', 'parse_pmlog', 'pick_graphics_card'],
    'platform_windows.icons': ['resolve_program_target', 'shell_item_image', 'legacy_icon_image', 'program_icon_image'],
    'platform_windows.programs': ['locate', 'program_roots', 'script_command', 'describe'],
    'platform_windows.shell': ['_powershell', 'shortcut_target', 'scan_start_menu', 'scan_programs'],
    'platform_windows.shortcuts': ['desktop_shortcut_path', 'create_shortcut'],
    'platform_windows.autostart': ['startup_script_path', 'startup_line', 'is_enabled', 'enable'],
    'platform_windows.editor_window': ['activate_window', 'brand_taskbar_identity', 'fit_to_work_area', 'open_native_window'],
    'platform_windows.session': ['locked'],
    'platform_windows.dialogs': ['ask_yes_no'],
    'platform_windows.processes': ['kill_tree', 'name_process', 'edit_script', 'open_target', 'open_path', 'notification_beep', 'spawn_options',
                                   'STOP_BY_KILLING_TREE'],
    'platform_windows.files': ['make_private'],
    'platform_windows.process_flags': ['NO_WINDOW', 'NEW_PROCESS_GROUP', 'DETACHED', 'NEW_CONSOLE'],
    'platform_windows.labels': ['MODULE_PROBE', 'AUTOSTART_NAME', 'SHORTCUT_NAME', 'LAUNCHER', 'ASKS_ABOUT_AUTOSTART', 'PROGRAM_SUFFIX',
                                'DEFAULT_PORT', 'RESETS_ON_OPEN', 'PLUGIN_ENV_KEEP', 'VENV_SCRIPTS', 'SCRIPT_EXTRA_SUFFIXES'],
    'platform_windows.tray': ['prepare'],
    'platform_windows.regional': ['clock_format'],
    'platform_windows.filelock': ['lock', 'unlock'],
}
WINDOWS_API = re.compile(r'ctypes\.(?:windll|WinDLL|wintypes)|\bwindll\b|\bwinreg\b|\bwinsound\b|\bmsvcrt\b|os\.startfile|'
                         r'\bMessageBoxW\b|\btaskkill\b|SHGetFolderPath|\bpycaw\b|\bwinrt\b|\bwin32pdh\b')
# shared modules that name a Windows library only as text: the package list of the diagnostics and the import probe of the setup
ALLOWED = {'diagnostics.py', 'setup_tool.py'}


class ImportTests(unittest.TestCase):
    def test_every_module_imports_here_and_has_the_names_the_host_uses(self):
        for name, attributes in EXPECTED.items():
            module = importlib.import_module(name)
            for attribute in attributes:
                self.assertTrue(hasattr(module, attribute), f'{name}.{attribute}')

    def test_every_file_of_the_package_is_covered_by_this_test(self):
        files = {f'platform_windows.{path.stem}' for path in (ROOT / 'host/platform_windows').glob('*.py') if path.stem != '__init__'}
        self.assertEqual(files - set(EXPECTED), set(), 'add the new module to EXPECTED')

    def test_the_names_are_the_ones_the_old_modules_exported_where_tests_and_callers_rely_on_them(self):
        import input_common
        from platform_windows import input as windows_input
        self.assertEqual(set(windows_input.VK), set(input_common.KEY_NAMES))
        for name in ('IS_WINDOWS', 'MOUSE_OPERATIONS', 'WINDOW_OPERATIONS', 'child_names', 'dry_hotkey'):
            self.assertTrue(hasattr(windows_input, name), name)


class LayeringTests(unittest.TestCase):
    def test_shared_modules_call_no_windows_api(self):
        offenders = []
        for path in sorted((ROOT / 'host').glob('*.py')):
            if path.name in ALLOWED:
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                code = line.split('#', 1)[0]
                if WINDOWS_API.search(code) and not code.strip().startswith(('"""', "'")):
                    offenders.append(f'{path.name}:{number}: {line.strip()[:80]}')
        self.assertEqual(offenders, [], 'Windows API calls belong in host/platform_windows')


if __name__ == '__main__':
    unittest.main()
