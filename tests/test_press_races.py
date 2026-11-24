"""Presses that cross a dimmed panel, a page change, slow typing, a busy worker or another thread."""
import copy
import os
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

    def test_api_feedback_on_a_dimmed_panel_leaves_it_dim(self):
        """/v1/feedback from a plugin: a lit panel the host thinks is dim would stay lit and eat the next tap."""
        daemon = make_daemon()
        daemon.dimmed = True
        daemon.handle_job(('feedback', 3, True))
        daemon.panel.feedback.assert_called_once_with(3, True, wake=False)
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


class PageChangeDuringWaitTests(unittest.TestCase):
    def test_a_press_step_after_a_wait_does_not_run_a_key_of_the_new_page(self):
        """Key 1 is [delay, press 2]. During the delay the page changes: key 2 of the new page must not run."""
        daemon = make_daemon()
        button(daemon)['actions'] = [{'type': 'delay', 'ms': 300}, {'type': 'press', 'id': 2}]
        status_key = next(b for b in daemon.config['profiles']['main']['pages']['status'] if b['id'] == 2)
        status_key['actions'] = [{'type': 'set', 'variable': 'ran', 'value': 'status key 2'}]

        def change_page():  # the main loop takes the lock the delay released and changes page
            with daemon.state_lock:
                daemon.switch_page('status')

        def wait(seconds):
            other = threading.Thread(target=change_page)
            other.start()
            other.join(2)
            return False

        daemon.stop.wait = wait
        with daemon.state_lock:
            ok = daemon.dispatch_press(1)
        self.assertEqual(daemon.page, 'status')
        self.assertIsNone(daemon.custom_vars.get('ran'))
        self.assertFalse(ok)
        self.assertIn('page changed', daemon.last_action['error'])

    def test_a_press_step_after_a_child_key_that_waits_does_not_run_a_key_of_the_new_page(self):
        """Key 1 is [press 3, press 2] and key 3 is [delay]. The page changes during key 3's delay: key 2 of the
        new page must not run."""
        daemon = make_daemon()
        button(daemon, 1)['actions'] = [{'type': 'press', 'id': 3}, {'type': 'press', 'id': 2}]
        button(daemon, 3)['actions'] = [{'type': 'delay', 'ms': 300}]
        status_key = next(b for b in daemon.config['profiles']['main']['pages']['status'] if b['id'] == 2)
        status_key['actions'] = [{'type': 'set', 'variable': 'ran', 'value': 'status key 2'}]

        def change_page():
            with daemon.state_lock:
                daemon.switch_page('status')

        def wait(seconds):
            other = threading.Thread(target=change_page)
            other.start()
            other.join(2)
            return False

        daemon.stop.wait = wait
        with daemon.state_lock:
            ok = daemon.dispatch_press(1)
        self.assertEqual(daemon.page, 'status')
        self.assertIsNone(daemon.custom_vars.get('ran'))
        self.assertFalse(ok)
        self.assertIn('page changed', daemon.last_action['error'])

    def test_a_child_key_that_changes_the_page_itself_after_its_wait_is_not_stopped(self):
        """Key 1 is [press 3, press 2] and key 3 is [delay, page status]. Nothing else changes the page, so key 2
        of the status page runs, as it does when the steps sit in key 1 itself."""
        daemon = make_daemon()
        button(daemon, 1)['actions'] = [{'type': 'press', 'id': 3}, {'type': 'press', 'id': 2}]
        button(daemon, 3)['actions'] = [{'type': 'delay', 'ms': 50}, {'type': 'page', 'page': 'status'}]
        status_key = next(b for b in daemon.config['profiles']['main']['pages']['status'] if b['id'] == 2)
        status_key['actions'] = [{'type': 'set', 'variable': 'ran', 'value': 'status key 2'}]
        with daemon.state_lock:
            ok = daemon.dispatch_press(1)
        self.assertIsNone(daemon.last_action['error'])
        self.assertTrue(ok)
        self.assertEqual(daemon.custom_vars.get('ran'), 'status key 2')

    def test_a_step_that_does_not_use_the_page_still_runs_after_the_page_changed(self):
        """Key 1 is [delay, set]: the opened program takes focus and the profile follows. The set step must run."""
        daemon = make_daemon()
        button(daemon)['actions'] = [{'type': 'delay', 'ms': 300}, {'type': 'set', 'variable': 'ran', 'value': 'yes'}]

        def change_page():
            with daemon.state_lock:
                daemon.switch_page('status')

        def wait(seconds):
            other = threading.Thread(target=change_page)
            other.start()
            other.join(2)
            return False

        daemon.stop.wait = wait
        with daemon.state_lock:
            ok = daemon.dispatch_press(1)
        self.assertEqual(daemon.page, 'status')
        self.assertEqual(daemon.custom_vars.get('ran'), 'yes')
        self.assertTrue(ok)


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

    def test_a_hotkey_key_during_slow_typing_does_not_hold_up_the_next_press(self):
        """The worker runs every press in turn: a hotkey that waits for slow typing would leave a page key behind it."""
        daemon = make_daemon()
        button(daemon, 1)['actions'] = [{'type': 'hotkey', 'keys': 'ctrl+c'}]
        button(daemon, 2)['actions'] = [{'type': 'page', 'page': 'status'}]
        daemon.input_lock.acquire()  # slow typing on another thread holds the keyboard
        worker = threading.Thread(target=daemon.worker_loop, daemon=True)
        with patch.object(deck, 'send_hotkey') as send:
            worker.start()
            daemon.enqueue(('press', 1, None, False, time.monotonic()))
            daemon.enqueue(('press', 2, None, False, time.monotonic()))
            both_done = threading.Thread(target=daemon.jobs.join, daemon=True)
            both_done.start()
            both_done.join(3)
            page = daemon.page
            daemon.input_lock.release()
            daemon.stop.set()
            worker.join(2)
        self.assertEqual(page, 'status', 'the page key waited behind the hotkey until the typing ended')
        send.assert_not_called()
        daemon.panel.feedback.assert_any_call(1, False)


class OfflineFileTriggerTests(unittest.TestCase):
    def test_a_file_trigger_on_an_offline_share_does_not_hold_up_presses(self):
        """os.stat on a share that is offline can hang for many seconds; the main loop runs it under the state lock."""
        daemon = make_daemon()
        offline = os.path.join('Z:' + os.sep, 'offline', 'x.txt')
        daemon.config['triggers'] = [{'when': {'type': 'file', 'path': offline}, 'actions': []}]
        button(daemon, 2)['actions'] = [{'type': 'page', 'page': 'status'}]
        share, asked, real_stat = threading.Event(), threading.Event(), os.stat

        def stat(path, *args, **kwargs):
            if path == offline:
                asked.set()
                share.wait(10)  # the share answers when the test ends
                raise OSError('The network path was not found')
            return real_stat(path, *args, **kwargs)

        def main_loop_tick():
            with daemon.state_lock:
                daemon.trigger_tick(1)

        worker = threading.Thread(target=daemon.worker_loop, daemon=True)
        with patch('daemon_ticks.os.stat', stat):
            tick = threading.Thread(target=main_loop_tick, daemon=True)
            tick.start()
            self.assertTrue(asked.wait(2))
            worker.start()
            daemon.enqueue(('press', 2, None, False, time.monotonic()))
            done = threading.Thread(target=daemon.jobs.join, daemon=True)
            done.start()
            done.join(3)
            page = daemon.page
            share.set()
            tick.join(2)
            daemon.stop.set()
            worker.join(2)
        self.assertEqual(page, 'status', 'the press waited for the file trigger on the offline share')


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
