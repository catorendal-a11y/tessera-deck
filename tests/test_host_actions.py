"""The clipboard, window and toggle actions: validation, what they run, their dry-run text and the editor entries."""
import ctypes
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from platform_marks import windows_only  # noqa: E402
import tesserad as deck
import host_support  # noqa: E402
import import_review
from platform_windows import input as win_input
from action_preview import preview


def make_daemon():
    daemon = host_support.test_daemon(port='TEST', no_focus=True)
    daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
    return daemon


def check(action):
    config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
    config['profiles']['main']['pages']['main'][0]['actions'] = [action]
    deck.validate_config(config)


class ValidationTests(unittest.TestCase):
    def test_good_actions_pass(self):
        for good in ({'type': 'clipboard', 'text': 'hi $(var:x)'}, {'type': 'clipboard', 'text': '', 'paste': True},
                     {'type': 'window', 'op': 'minimize'}, {'type': 'window', 'op': 'topmost', 'process': 'notepad.exe'},
                     {'type': 'window', 'op': 'focus', 'process': 'code.exe'}, {'type': 'window', 'op': 'next_monitor'},
                     {'type': 'toggle', 'variable': 'mode'}, {'type': 'toggle', 'variable': 'mic', 'values': ['live', 'muted']}):
            check(good)

    def test_bad_actions_are_refused(self):
        for bad in ({'type': 'clipboard'}, {'type': 'clipboard', 'text': 5}, {'type': 'clipboard', 'text': 'a', 'paste': 'yes'},
                    {'type': 'window'}, {'type': 'window', 'op': 'fly'}, {'type': 'window', 'op': 'focus'},
                    {'type': 'window', 'op': 'close', 'process': 7}, {'type': 'window', 'op': 'close', 'process': 'x' * 261},
                    {'type': 'toggle'}, {'type': 'toggle', 'variable': 'bad name'},
                    {'type': 'toggle', 'variable': 'm', 'values': ['a']}, {'type': 'toggle', 'variable': 'm', 'values': ['a', 'a']},
                    {'type': 'toggle', 'variable': 'm', 'values': ['a', 2]}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                check(bad)

    def test_set_needs_a_name_that_can_be_read_back(self):
        check({'type': 'set', 'variable': 'mode.1', 'value': 'on $(var:x)'})
        for bad in ({'type': 'set', 'variable': 'Mode 1', 'value': 'a'}, {'type': 'set', 'variable': 'tæller'},
                    {'type': 'set', 'variable': 'm', 'value': 'x' * 1001}, {'type': 'set', 'variable': 'm', 'value': True}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                check(bad)


class RunTests(unittest.TestCase):
    def test_toggle_flips_a_variable_starting_with_the_first_value(self):
        daemon = make_daemon()
        action = {'type': 'toggle', 'variable': 'mic', 'values': ['live', 'muted']}
        seen = []
        for _ in range(3):
            daemon.run_action(action)
            seen.append(daemon.custom_vars['mic'])
        self.assertEqual(seen, ['live', 'muted', 'live'])
        daemon.custom_vars['mode'] = 'something else'
        daemon.run_action({'type': 'toggle', 'variable': 'mode'})
        self.assertEqual(daemon.custom_vars['mode'], 'on')

    def test_clipboard_expands_variables_and_pastes_only_when_asked(self):
        daemon = make_daemon()
        daemon.custom_vars['name'] = 'Ada'
        with patch.object(deck, 'set_clipboard') as clip, patch.object(deck, 'send_hotkey') as keys:
            daemon.run_action({'type': 'clipboard', 'text': 'Hi $(var:name)'})
            keys.assert_not_called()
            daemon.run_action({'type': 'clipboard', 'text': 'x', 'paste': True})
        self.assertEqual([call.args[0] for call in clip.call_args_list], ['Hi Ada', 'x'])
        keys.assert_called_once_with('ctrl+v')

    def test_window_runs_under_the_input_lock_and_a_missing_window_fails_the_key(self):
        daemon = make_daemon()
        with patch.object(deck, 'window_action', return_value=True) as act:
            daemon.run_action({'type': 'window', 'op': 'focus', 'process': 'code.exe'})
        act.assert_called_once_with('focus', 'code.exe')
        with patch.object(deck, 'window_action', return_value=False), self.assertRaises(ValueError):
            daemon.run_action({'type': 'window', 'op': 'close'})


@unittest.skipUnless(win_input.IS_WINDOWS, 'Windows only')
class WindowsHelperTests(unittest.TestCase):
    def test_each_window_operation_sends_the_right_call(self):
        user32 = Mock(GetForegroundWindow=Mock(return_value=42), GetWindowLongW=Mock(return_value=0x8))
        with patch.object(win_input, 'user32', user32), patch.object(win_input, 'bring_to_front') as front, \
                patch.object(win_input, 'send_hotkey') as keys:
            for op in ('minimize', 'maximize', 'restore'):
                self.assertTrue(win_input.window_action(op))
            self.assertEqual([c.args for c in user32.ShowWindow.call_args_list], [(42, 6), (42, 3), (42, 9)])
            win_input.window_action('close')
            user32.PostMessageW.assert_called_once_with(42, 0x10, 0, 0)
            win_input.window_action('topmost')  # already on top: it comes off
            self.assertEqual(user32.SetWindowPos.call_args.args[:2], (42, -2))
            user32.GetWindowLongW.return_value = 0
            win_input.window_action('topmost')
            self.assertEqual(user32.SetWindowPos.call_args.args[:2], (42, -1))
            win_input.window_action('next_monitor')
            front.assert_called_once_with(user32, 42)
            keys.assert_called_once_with('win+shift+right')
            with self.assertRaises(ValueError):
                win_input.window_action('fly')

    def test_a_named_process_without_a_window_does_nothing(self):
        user32 = Mock()
        with patch.object(win_input, 'user32', user32), patch.object(win_input, 'process_window', return_value=None):
            self.assertFalse(win_input.window_action('close', 'nothing.exe'))
        user32.PostMessageW.assert_not_called()

    def test_clipboard_text_is_utf16_with_windows_line_ends(self):
        buffer = ctypes.create_string_buffer(64)
        user32 = Mock(OpenClipboard=Mock(side_effect=[0, 1]))
        kernel32 = Mock(GlobalAlloc=Mock(return_value=7), GlobalLock=Mock(return_value=ctypes.addressof(buffer)))
        with patch.object(win_input, 'user32', user32), patch.object(win_input, 'kernel32', kernel32):
            win_input.set_clipboard('a\nø', wait=lambda seconds: None)  # the first open fails: it tries again
        expected = 'a\r\nø\0'.encode('utf-16-le')
        self.assertEqual(kernel32.GlobalAlloc.call_args.args[1], len(expected))
        self.assertEqual(buffer.raw[:len(expected)], expected)
        user32.SetClipboardData.assert_called_once_with(13, 7)
        user32.CloseClipboard.assert_called_once()

    def test_a_busy_clipboard_raises(self):
        user32 = Mock(OpenClipboard=Mock(return_value=0))
        with patch.object(win_input, 'user32', user32), self.assertRaises(OSError):
            win_input.set_clipboard('x', tries=2, wait=lambda seconds: None)
        user32.CloseClipboard.assert_not_called()


class PreviewTests(unittest.TestCase):
    def test_dry_run_explains_each_new_action(self):
        steps = preview([{'type': 'clipboard', 'text': 'Hi $(var:name)', 'paste': True},
                         {'type': 'window', 'op': 'topmost'}, {'type': 'window', 'op': 'focus', 'process': 'code.exe'},
                         {'type': 'toggle', 'variable': 'mic', 'values': ['live', 'muted']}],
                        {'var:name': 'Ada', 'var:mic': 'live'})['steps']
        self.assertEqual([step['text'] for step in steps],
                         ['Copy "Hi Ada" to the clipboard and paste it', 'Toggle always on top for the window in front',
                          'Bring to the front the window of code.exe', 'Switch variable mic to "muted"'])
        self.assertTrue(all(step['ok'] for step in steps))

    def test_automatic_window_and_clipboard_actions_are_shown_on_import(self):
        config = {'profiles': {}, 'triggers': [{'when': {'type': 'startup'},
                                                'actions': [{'type': 'window', 'op': 'close'}, {'type': 'clipboard', 'text': 'x'}]}]}
        self.assertEqual([item['kind'] for item in import_review.review(config)], ['window', 'clipboard'])


class EditorTests(unittest.TestCase):
    def test_editor_and_catalogue_know_the_new_types(self):
        core = (ROOT / 'host/editor/core.js').read_text(encoding='utf-8')
        for kind in ('clipboard', 'window', 'toggle'):
            self.assertIn(f'\n  {kind}:{{name:', core)
        catalog = json.loads((ROOT / 'host/action_packs.json').read_text(encoding='utf-8'))
        used = {action['type'] for pack in catalog['packs'] for action in pack['actions']}
        self.assertTrue({'clipboard', 'window'} <= used)
        for pack in catalog['packs']:
            for action in pack['actions']:
                if action['type'] in ('clipboard', 'window'):
                    check(action)


class ScriptStepTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def make(self, name, text=''):
        path = Path(self.folder.name) / name
        path.write_text(text, encoding='utf-8')
        return str(path)

    @windows_only
    def test_validation(self):
        check({'type': 'script', 'path': 'C:\\tools\\a.ps1', 'timeout': 10})
        for bad in ({'type': 'script'}, {'type': 'script', 'path': 5}, {'type': 'script', 'path': 'C:\\a.exe'},
                    {'type': 'script', 'path': ''}, {'type': 'script', 'path': 'a.py', 'timeout': 0},
                    {'type': 'script', 'path': 'a' * 1100 + '.py'}, {'type': 'script', 'path': 'scripts\\a.py'},
                    {'type': 'script', 'path': 'C:\\100%done\\a.cmd'}):
            with self.assertRaises(ValueError, msg=bad):
                check(bad)
        check({'type': 'script', 'path': '%USERPROFILE%\\a.py'})
        check({'type': 'script', 'path': ' "C:\\tools\\a.ps1" '})  # as pasted from Explorer's Copy as path
        with self.assertRaises(ValueError):
            check({'type': 'script', 'path': 'C:\\%NAME%\\a.cmd'})

    @windows_only
    def test_a_variable_that_is_not_set_fails_the_key_and_not_the_configuration(self):
        from action_runner import script_path
        with patch.dict(os.environ, {'TESSERA_SET': self.folder.name}):
            os.environ.pop('TESSERA_UNSET', None)
            for name in ('a.bat', 'a.py'):  # the same configuration loads on a PC without the variable
                check({'type': 'script', 'path': f'%TESSERA_UNSET%\\{name}'})
                with self.assertRaisesRegex(ValueError, '%TESSERA_UNSET% is not set on this PC'):
                    script_path(f'%TESSERA_UNSET%\\{name}')
            found = self.make('a.py', '')
            self.assertEqual(script_path(' "%TESSERA_SET%\\a.py" '), found)
            # only %NAME% is a variable: a folder may be named $TESSERA_SET
            with self.assertRaisesRegex(ValueError, r'not found: C:\\\$TESSERA_SET\\a\.py'):
                script_path('C:\\$TESSERA_SET\\a.py')

    def test_a_script_step_waits_on_the_slow_lane(self):
        self.assertTrue(make_daemon().waits([{'type': 'script', 'path': 'C:\\a.py'}]))

    def test_interpreter_choice(self):
        from platform_windows.programs import script_command
        which = {'py.exe': 'C:\\py.exe', 'pyw.exe': 'C:\\pyw.exe', 'powershell.exe': 'C:\\ps.exe', 'node.exe': 'C:\\node.exe'}.get
        pick = lambda path, **kw: script_command(path, which=which, registry=lambda name: None,
                                                 association=lambda suffix: None, roots=lambda: [], **kw)
        self.assertEqual(pick('C:\\s\\a.py'), ['C:\\py.exe', '-3', 'C:\\s\\a.py'])
        self.assertEqual(pick('C:\\s\\a.pyw')[0], 'C:\\pyw.exe')
        self.assertEqual(pick('C:\\s\\a.bat'), '"C:\\s\\a.bat"')
        with self.assertRaisesRegex(ValueError, '%'):
            pick('C:\\s\\100%a.bat')
        self.assertEqual(pick('C:\\s\\a.js'), ['C:\\node.exe', 'C:\\s\\a.js'])
        ps = pick('C:\\s\\a.ps1')
        self.assertEqual(ps[:6], ['C:\\ps.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File'])
        with self.assertRaisesRegex(ValueError, 'AutoHotkey'):
            pick('C:\\s\\a.ahk')
        with self.assertRaises(ValueError):
            pick('C:\\s\\a.vbs')

    def test_autohotkey_uses_the_file_association_then_app_paths(self):
        from platform_windows.programs import script_command
        exe = self.make('AutoHotkey64.exe')
        via_association = script_command('C:\\s\\a.ahk', which=lambda name: None, registry=lambda name: None,
                                        association=lambda suffix: f'"{exe}" "%1" %*')
        self.assertEqual(via_association, [exe, 'C:\\s\\a.ahk'])
        via_registry = script_command('C:\\s\\a.ahk', which=lambda name: None,
                                      registry=lambda name: exe if name == 'AutoHotkey64.exe' else None,
                                      association=lambda suffix: None)
        self.assertEqual(via_registry, [exe, 'C:\\s\\a.ahk'])

    def test_a_per_user_autohotkey_is_found_without_the_file_association(self):
        # The per-user installer puts AutoHotkey in %LOCALAPPDATA%\Programs and adds neither App Paths nor PATH
        from platform_windows.programs import script_command
        programs = Path(self.folder.name)
        (programs / 'AutoHotkey' / 'v2').mkdir(parents=True)
        (programs / 'AutoHotkey' / 'v2' / 'AutoHotkey64.exe').write_bytes(b'')
        found = script_command('C:\\s\\a.ahk', which=lambda name: None, registry=lambda name: None,
                               association=lambda suffix: None, roots=lambda: [Path('C:\\nowhere'), programs])
        self.assertEqual(found, [str(programs / 'AutoHotkey' / 'v2' / 'AutoHotkey64.exe'), 'C:\\s\\a.ahk'])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows only')
    def test_runs_in_its_own_folder_and_reports_failures(self):
        from action_runner import CommandFailed, run_script
        import threading
        ok = self.make('ok.cmd', '@echo off\r\ncd > "%~dp0cwd.txt"\r\n')
        run_script(ok, 10, threading.Event())
        self.assertEqual((Path(self.folder.name) / 'cwd.txt').read_text().strip().lower(), self.folder.name.lower())
        for folder in ('a&b', 'caret^x', 'x&mkdir,INJECTED&'):  # cmd must not parse these characters
            (Path(self.folder.name) / folder).mkdir()
            run_script(self.make(f'{folder}\\t.cmd', '@echo off\r\ncd > "%~dp0cwd.txt"\r\n'), 10, threading.Event())
            self.assertTrue((Path(self.folder.name) / folder / 'cwd.txt').exists(), folder)
        self.assertFalse((Path(self.folder.name) / 'INJECTED').exists())
        bad = self.make('bad.cmd', '@echo off\r\necho broken 1>&2\r\nexit /b 3\r\n')
        with self.assertRaisesRegex(CommandFailed, 'code 3.*broken'):
            run_script(bad, 10, threading.Event())
        with self.assertRaisesRegex(CommandFailed, 'not found'):
            run_script(str(Path(self.folder.name) / 'missing.cmd'), 10, threading.Event())
        with self.assertRaisesRegex(CommandFailed, 'full path'):
            run_script('relative.cmd', 10, threading.Event())

    def test_daemon_runs_the_step_and_turns_failures_into_errors(self):
        from action_runner import CommandFailed
        daemon = make_daemon()
        with patch.object(deck, 'run_script') as run:
            daemon.run_action({'type': 'script', 'path': 'C:\\a.py', 'timeout': 7})
        self.assertEqual(run.call_args.args[:2], ('C:\\a.py', 7))
        with patch.object(deck, 'run_script', side_effect=CommandFailed('boom')):
            with self.assertRaisesRegex(RuntimeError, 'boom'):
                daemon.run_action({'type': 'script', 'path': 'C:\\a.py'})

    def test_dry_run_reports_file_and_interpreter(self):
        found = self.make('a.js')
        with patch('action_preview.script_command', return_value=['C:\\node.exe', found]):
            result = preview([{'type': 'script', 'path': found}], {})
        self.assertTrue(result['ok'])
        self.assertIn('node.exe', result['steps'][0]['text'])
        batch = self.make('t 1.bat')
        with patch('action_preview.script_command', return_value=f'"{batch}"'):  # a batch file is one command line for cmd
            self.assertIn('with cmd (', preview([{'type': 'script', 'path': batch}], {})['steps'][0]['text'])
        missing = preview([{'type': 'script', 'path': str(Path(self.folder.name) / 'none.js')}], {})
        self.assertFalse(missing['ok'])
        self.assertIn('not found', missing['steps'][0]['text'])
        with patch('action_preview.script_command', side_effect=ValueError('Node.js (node) was not found on this PC')):
            self.assertFalse(preview([{'type': 'script', 'path': found}], {})['ok'])

    def test_import_review_flags_and_strips_scripts(self):
        config = {'default_profile': 'P', 'profiles': {'P': {'match': [], 'pages': {'a': [
            {'id': 1, 'label': 'S', 'actions': [{'type': 'script', 'path': 'C:\\x\\a.ps1'}]}]}}}}
        found = import_review.review(config)
        self.assertEqual([(item['kind'], item['risk']) for item in found], [('script', 'high')])
        stripped = import_review.strip_executable(config)
        self.assertEqual(stripped['profiles']['P']['pages']['a'][0]['actions'], [])

    def test_editor_has_the_step(self):
        core = (ROOT / 'host/editor/core.js').read_text(encoding='utf-8')
        self.assertIn('\n  script:{name:', core)


@windows_only
class AgentTerminalTests(unittest.TestCase):
    def test_the_agent_keys_open_the_terminal_in_the_users_folder_not_in_tessera(self):
        # The host runs from the Tessera folder, so %CD% in the command is that folder. Ask cmd what the folder
        # in each command becomes there.
        import re
        import subprocess
        found = []
        for name in ('host/profiles.default.json', 'host/action_packs.json'):
            for match in re.finditer(r'nt -d \\"([^"\\]+)\\"', (ROOT / name).read_text(encoding='utf-8')):
                found.append(match[1])
        self.assertGreaterEqual(len(found), 5)
        for folder in found:
            shown = subprocess.run(f'echo {folder}', shell=True, cwd=ROOT, capture_output=True, text=True).stdout.strip()
            self.assertEqual(shown, os.environ['USERPROFILE'], folder)


if __name__ == '__main__':
    unittest.main()
