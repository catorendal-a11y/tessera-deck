"""Presses every button of every bundled profile through the host with the OS side mocked."""
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck


def make_daemon():
    daemon = deck.Daemon(types.SimpleNamespace(profiles=str(ROOT / 'host/profiles.default.json'), port='TEST',
                                               verbose=False, no_focus=True, deck_only=True))
    daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
    daemon.stop.clear()
    return daemon


def free_slots(daemon, count):
    """Empty `count` slots on the shown page (the bundled home page is full) and return them."""
    page = daemon.config['profiles']['main']['pages'][daemon.page]
    del page[:count]
    return page, [i for i in range(1, 18) if all(b['id'] != i for b in page)][:count]


class ButtonTests(unittest.TestCase):
    def setUp(self):
        patches = [patch.object(deck, name, Mock()) for name in ('send_hotkey', 'send_text', 'focus_existing_process')]
        patches += [patch.object(deck.os, 'startfile', Mock(), create=True), patch.object(deck.subprocess, 'Popen', Mock()),
                    patch.object(deck.subprocess, 'run', Mock(return_value=Mock(returncode=0))),
                    patch.object(deck.urllib.request, 'urlopen', Mock())]
        self.mocks = [p.start() for p in patches]
        self.addCleanup(lambda: [p.stop() for p in patches])

    def every_button(self, daemon):
        for name, profile in daemon.config['profiles'].items():
            for page, buttons in profile['pages'].items():
                for button in buttons + profile.get('pinned', []):
                    yield name, page, button

    def test_every_bundled_button_runs_and_is_confirmed_green(self):
        daemon = make_daemon()
        total = 0
        for name, page, button in self.every_button(daemon):
            with self.subTest(profile=name, page=page, id=button['id'], label=button['label']):
                daemon.profile, daemon.page = name, page
                daemon.folder_stack.clear()
                daemon.panel.feedback.reset_mock()
                daemon.last_action = None
                if 'gauge' in button:  # gauges have no actions; a press must still be harmless
                    self.assertEqual(button.get('actions', []), [])
                self.assertTrue(daemon.dispatch_press(button['id']), daemon.last_action)
                daemon.panel.feedback.assert_called_once_with(button['id'], True)
                self.assertTrue(daemon.last_action['ok'])
                total += 1
        self.assertGreater(total, 100)

    def test_every_button_reaches_the_panel_in_a_valid_layout(self):
        daemon = make_daemon()
        for name, profile in daemon.config['profiles'].items():
            for page in profile['pages']:
                with self.subTest(profile=name, page=page):
                    daemon.profile, daemon.page = name, page
                    buttons = daemon.current_buttons()
                    ids = [b['id'] for b in buttons]
                    self.assertEqual(len(ids), len(set(ids)))
                    self.assertTrue(all(1 <= i <= 18 for i in ids))
                    for b in buttons:
                        self.assertTrue(b['label'], b)
                        self.assertLessEqual(len(b['label'].encode()), 24)
                        self.assertRegex(b['color'], r'^#[0-9A-Fa-f]{6}$')
                        if 'gauge' in b:
                            self.assertTrue(0 <= b['gauge']['p'] <= 100)
                            self.assertLessEqual(len(b['gauge']['t']), 7)
                    payload = json.dumps({'buttons': buttons}, ensure_ascii=True, separators=(',', ':'))
                    self.assertLessEqual(len(payload.encode()), 8192)

    def test_every_action_type_does_what_it_says(self):
        daemon = make_daemon()
        send_hotkey, send_text, _, startfile, popen, run, urlopen = self.mocks
        page = next(iter(daemon.config['profiles']['main']['pages']))
        daemon.profile, daemon.page = 'main', page
        other = [p for p in daemon.config['profiles']['main']['pages'] if p != page][0]
        daemon.run_action({'type': 'hotkey', 'keys': 'ctrl+c'})
        send_hotkey.assert_called_with('ctrl+c')
        daemon.custom_vars['who'] = 'Ada'
        daemon.run_action({'type': 'text', 'text': 'Hi $(var:who)'})
        send_text.assert_called_with('Hi Ada')
        daemon.run_action({'type': 'shell', 'command': 'echo hi'})
        run.assert_called_once()
        urlopen.return_value.__enter__ = Mock(return_value=Mock())
        urlopen.return_value.__exit__ = Mock(return_value=False)
        daemon.run_action({'type': 'http', 'url': 'http://127.0.0.1:1/x', 'method': 'POST', 'body': 'b'})
        urlopen.assert_called_once()
        daemon.run_action({'type': 'delay', 'ms': 0})
        daemon.run_action({'type': 'folder', 'page': other})
        self.assertEqual((daemon.page, daemon.folder_stack), (other, [page]))
        daemon.run_action({'type': 'back'})
        self.assertEqual((daemon.page, daemon.folder_stack), (page, []))
        daemon.run_action({'type': 'back'})  # nothing to go back to: stays put
        self.assertEqual(daemon.page, page)
        daemon.run_action({'type': 'page', 'page': other})
        self.assertEqual((daemon.page, daemon.folder_stack), (other, []))
        daemon.run_action({'type': 'home'})
        self.assertEqual((daemon.profile, daemon.page), ('main', next(iter(daemon.config['profiles']['main']['pages']))))
        target = [p for p in daemon.config['profiles'] if p != 'main'][0]
        daemon.run_action({'type': 'profile', 'profile': target})
        self.assertEqual(daemon.profile, target)
        daemon.switch_profile('main')
        daemon.run_action({'type': 'set', 'variable': 'claude', 'value': 'working'})
        self.assertEqual(daemon.custom_vars['claude'], 'working')
        with self.assertRaises(ValueError):
            daemon.run_action({'type': 'nope'})
        with self.assertRaises(ValueError):
            daemon.run_action({'type': 'page', 'page': 'does-not-exist'})

    def test_open_action_focuses_a_running_program_before_starting_it(self):
        daemon = make_daemon()
        startfile, focus = self.mocks[3], self.mocks[2]
        with patch.object(deck, 'IS_WINDOWS', True):
            focus.return_value = True
            daemon.run_action({'type': 'open', 'target': 'C:\\a.exe', 'process': 'a.exe', 'reuse': True})
            startfile.assert_not_called()
            focus.return_value = False
            daemon.run_action({'type': 'open', 'target': 'C:\\a.exe', 'process': 'a.exe', 'reuse': True})
            startfile.assert_called_once()
            startfile.reset_mock()
            daemon.run_action({'type': 'open', 'target': 'C:\\a.exe'})  # no reuse: always starts
            startfile.assert_called_once()

    def test_failures_are_reported_red_and_stop_the_remaining_steps(self):
        daemon = make_daemon()
        daemon.panel.feedback.reset_mock()
        self.mocks[0].side_effect = ValueError('bad key')
        page, (slot,) = free_slots(daemon, 1)
        page.append({'id': slot, 'label': 'X', 'icon': 'ok', 'actions': [
            {'type': 'hotkey', 'keys': 'ctrl+c'}, {'type': 'text', 'text': 'never'}]})
        self.assertFalse(daemon.dispatch_press(slot))
        daemon.panel.feedback.assert_called_once_with(slot, False)
        self.mocks[1].assert_not_called()
        self.assertIn('bad key', daemon.last_action['error'])

    def test_unknown_button_and_press_loops_are_rejected(self):
        daemon = make_daemon()
        page, (a, b) = free_slots(daemon, 2)
        self.assertFalse(daemon.dispatch_press(99))
        daemon.panel.feedback.assert_called_with(99, False)
        page.append({'id': a, 'label': 'A', 'icon': 'ok', 'actions': [{'type': 'press', 'id': b}]})
        page.append({'id': b, 'label': 'B', 'icon': 'ok', 'actions': [{'type': 'press', 'id': a}]})
        self.assertFalse(daemon.dispatch_press(a))
        self.assertEqual(daemon.active_press, [])  # the guard unwinds fully

    def test_toggle_buttons_cycle_through_all_states_and_wrap(self):
        daemon = make_daemon()
        page, (slot,) = free_slots(daemon, 1)
        page.append({'id': slot, 'label': 'T', 'icon': 'ok', 'actions': [], 'states': [
            {'label': 'one'}, {'label': 'two'}, {'label': 'three'}]})
        seen = []
        for _ in range(4):
            seen.append(next(b['label'] for b in daemon.current_buttons() if b['id'] == slot))
            daemon.dispatch_press(slot)
        self.assertEqual(seen, ['one', 'two', 'three', 'one'])
        daemon.set_button_state(slot, 2)
        self.assertEqual(next(b['label'] for b in daemon.current_buttons() if b['id'] == slot), 'three')
        with self.assertRaises(ValueError):
            daemon.set_button_state(slot, 5)


if __name__ == '__main__':
    unittest.main()
