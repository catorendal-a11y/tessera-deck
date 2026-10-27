"""Double press (Stream Deck "Key Logic"): a key with double_actions waits briefly to tell one tap from two."""
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck


def set_variable(value):
    return [{'type': 'set', 'variable': 'tap', 'value': value}]


class DoublePressTests(unittest.TestCase):
    def setUp(self):
        self.daemon = deck.Daemon(types.SimpleNamespace(profiles=str(ROOT / 'host/profiles.default.json'), port='TEST',
                                                        verbose=False, no_focus=True, deck_only=True))
        daemon = self.daemon
        daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
        daemon.stop.clear()
        daemon.profile, daemon.page = 'main', 'main'
        self.scheduled = []
        daemon.schedule_job = lambda job, delay: self.scheduled.append((job, delay))
        button = next(b for b in daemon.config['profiles']['main']['pages']['main'] if b['id'] == 1)
        button['actions'], button['double_actions'] = set_variable('single'), set_variable('double')
        self.button = button

    def press(self):
        self.daemon.handle_job(('press', 1, None, False))

    def tap(self):
        return self.daemon.custom_vars.get('tap')

    def test_a_single_tap_runs_only_after_the_waiting_time(self):
        self.press()
        self.assertIsNone(self.tap())
        (job, delay), = self.scheduled
        self.assertEqual((job[0], delay), ('single-due', deck.DOUBLE_PRESS_SECONDS))
        self.daemon.handle_job(job)
        self.assertEqual(self.tap(), 'single')

    def test_two_taps_run_the_double_actions_and_never_the_single_ones(self):
        self.press()
        self.press()
        self.assertEqual(self.tap(), 'double')
        self.daemon.handle_job(self.scheduled[0][0])  # the first tap's timer fires late
        self.assertEqual(self.tap(), 'double')

    def test_a_third_tap_starts_over(self):
        self.press()
        self.press()
        self.press()
        self.assertEqual(len(self.scheduled), 2)
        self.daemon.handle_job(self.scheduled[1][0])
        self.assertEqual(self.tap(), 'single')

    def test_the_layout_tells_the_panel_which_keys_have_a_double_press(self):
        shown = {b['id']: b for b in self.daemon.current_buttons()}
        self.assertTrue(shown[1]['double'])
        self.assertNotIn('double', shown[2])

    def test_a_key_without_double_actions_still_acts_at_once(self):
        del self.button['double_actions']
        self.press()
        self.assertEqual(self.tap(), 'single')
        self.assertEqual(self.scheduled, [])

    def test_changing_page_drops_the_waiting_tap(self):
        self.press()
        self.daemon.page = 'other'
        self.daemon.handle_job(self.scheduled[0][0])
        self.assertIsNone(self.tap())

    def test_a_long_press_does_not_wait(self):
        self.button['hold_actions'] = set_variable('held')
        self.daemon.handle_job(('press', 1, None, True))
        self.assertEqual(self.tap(), 'held')
        self.assertEqual(self.scheduled, [])

    def test_the_actions_are_validated_like_the_others(self):
        config = json.loads(json.dumps(self.daemon.config))
        deck.validate_config(config)
        next(b for b in config['profiles']['main']['pages']['main'] if b['id'] == 1)['double_actions'] = [
            {'type': 'hotkey', 'keys': 'not-a-key'}]
        with self.assertRaises(ValueError):
            deck.validate_config(config)


class DoublePressTouchpointTests(unittest.TestCase):
    def test_import_review_lists_double_press_actions_for_approval(self):
        import import_review
        config = {'profiles': {'Main': {'pages': {'main': [{'id': 1, 'label': 'A', 'actions': [],
                                                           'double_actions': [{'type': 'shell', 'command': 'calc'}]}]}}}}
        found = [(name, key) for name, _, key, _ in import_review.iter_actions(config)]
        self.assertTrue(any(key == 'double_actions' and name.endswith('(double press)') for name, key in found))

    def test_the_dry_run_explains_double_actions(self):
        import tessera_app
        editor = tessera_app.Editor.__new__(tessera_app.Editor)
        editor.status = lambda: {'variables': {}}
        result = tessera_app.Editor.dry_run(editor, {'actions': [], 'double_actions': [{'type': 'hotkey', 'keys': 'ctrl+c'}]})
        self.assertEqual(result['double_actions']['steps'][0]['text'], 'Press ctrl+c')


if __name__ == '__main__':
    unittest.main()
