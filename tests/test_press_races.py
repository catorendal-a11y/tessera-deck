"""Presses that cross a dimmed panel, a page change, slow typing, a busy worker or another thread."""
import copy
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck
import host_support  # noqa: E402


def make_daemon():
    daemon = host_support.test_daemon(port='TEST', no_focus=True)
    daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
    daemon.stop.clear()
    daemon.profile, daemon.page = 'main', 'main'
    return daemon


def button(daemon, button_id=1):
    return next(b for b in daemon.config['profiles']['main']['pages']['main'] if b['id'] == button_id)


class DimmedFeedbackTests(unittest.TestCase):
    def test_feedback_without_wake_only_flashes_the_key(self):
        panel = deck.PanelSerial.__new__(deck.PanelSerial)
        panel.send_line = Mock()
        panel.feedback(7, False, wake=False)
        self.assertEqual([call.args[0] for call in panel.send_line.call_args_list], ['AD_FEEDBACK alert 7'])

    def test_a_trigger_press_on_a_dimmed_panel_leaves_it_dim(self):
        daemon = make_daemon()
        daemon.dimmed = True
        button(daemon)['actions'] = [{'type': 'set', 'variable': 'x', 'value': '1'}]
        daemon.start_actions([{'type': 'press', 'id': 1}])
        daemon.panel.feedback.assert_called_once_with(1, True, wake=False)
        self.assertTrue(daemon.dimmed)

    def test_an_awake_panel_still_gets_the_wake_with_its_feedback(self):
        daemon = make_daemon()
        daemon.give_feedback(3, True)
        daemon.panel.feedback.assert_called_once_with(3, True)

    def test_a_rejected_slow_press_without_a_panel_does_not_raise(self):
        daemon = make_daemon()
        button(daemon)['actions'] = [{'type': 'delay', 'ms': 10}]
        daemon.slow_running.add(('main', 'main', 1))
        daemon.panel = None
        self.assertFalse(daemon.start_press(1))


class SlowPressPageTests(unittest.TestCase):
    def test_a_slow_press_does_not_run_after_the_page_changed(self):
        daemon = make_daemon()
        daemon.dispatch_press = Mock()
        daemon.slow_slots.acquire()
        daemon.page = 'other'
        daemon.run_slow_press(1, False, ('main', 'main', 1))
        daemon.dispatch_press.assert_not_called()
        daemon.panel.feedback.assert_called_once_with(1, False)


class InputLockTests(unittest.TestCase):
    def test_waiting_for_slow_typing_releases_the_state_lock(self):
        daemon = make_daemon()
        daemon.input_lock.acquire()  # slow typing on another thread holds the keyboard
        free = threading.Event()

        def hotkey():
            with daemon.state_lock:
                daemon.run_action({'type': 'hotkey', 'keys': 'ctrl+c'})

        with patch.object(deck, 'send_hotkey') as send:
            worker = threading.Thread(target=hotkey, daemon=True)
            worker.start()
            for _ in range(100):
                if daemon.state_lock.acquire(blocking=False):
                    daemon.state_lock.release()
                    free.set()
                    break
                time.sleep(0.01)
            daemon.input_lock.release()
            worker.join(2)
        self.assertTrue(free.is_set(), 'the state lock stayed held while waiting for the keyboard')
        send.assert_called_once_with('ctrl+c')
        self.assertFalse(daemon.input_lock.locked())


class DoubleTapTimingTests(unittest.TestCase):
    def setUp(self):
        self.daemon = daemon = make_daemon()
        self.scheduled = []
        daemon.schedule_job = lambda job, delay: self.scheduled.append(job)
        b = button(daemon)
        b['actions'] = [{'type': 'set', 'variable': 'tap', 'value': 'single'}]
        b['double_actions'] = [{'type': 'set', 'variable': 'tap', 'value': 'double'}]

    def test_two_taps_seconds_apart_are_two_single_taps(self):
        now = time.monotonic()
        self.daemon.handle_job(('press', 1, None, False, now - 2))
        self.daemon.handle_job(('press', 1, None, False, now))  # the busy worker handles both at once
        self.assertEqual(self.daemon.custom_vars.get('tap'), 'single')
        self.daemon.handle_job(self.scheduled[0])  # the first timer finds nothing left to run
        self.daemon.custom_vars['tap'] = None
        self.daemon.handle_job(self.scheduled[1])
        self.assertEqual(self.daemon.custom_vars.get('tap'), 'single')

    def test_a_dropped_single_due_forgets_the_waiting_tap(self):
        daemon = self.daemon
        daemon.handle_job(('press', 1, None, False, time.monotonic()))
        daemon.enqueue = Mock(return_value=False)  # the queue was full when the timer fired
        daemon.enqueue_later(self.scheduled[0])
        self.assertEqual(daemon.pending_single, {})


class ProfileSwitchTests(unittest.TestCase):
    def test_switching_to_an_identical_profile_still_pushes_the_page(self):
        daemon = make_daemon()
        daemon.config['profiles']['copy'] = copy.deepcopy(daemon.config['profiles']['main'])
        daemon.push_page = Mock()
        daemon.switch_profile('copy')
        daemon.push_page.assert_called_once_with(force=True)


class StateSetThreadTests(unittest.TestCase):
    def test_each_thread_has_its_own_set_of_states_set_by_actions(self):
        daemon = make_daemon()
        daemon.state_set_by_action.add('mine')
        seen = []
        thread = threading.Thread(target=lambda: seen.append(set(daemon.state_set_by_action)))
        thread.start()
        thread.join(2)
        self.assertEqual(seen, [set()])
        self.assertEqual(daemon.state_set_by_action, {'mine'})


if __name__ == '__main__':
    unittest.main()
