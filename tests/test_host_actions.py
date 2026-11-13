"""The clipboard, window and toggle actions: validation, what they run, their dry-run text and the editor entries."""
import ctypes
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck
import host_support  # noqa: E402
import import_review
import win_input
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


if __name__ == '__main__':
    unittest.main()
