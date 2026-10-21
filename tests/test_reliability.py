"""Queue backpressure, the slow lane, stale input, reconnect policy and bounded command execution."""
from pathlib import Path
import sys
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck
from action_runner import Busy, CommandFailed, run_command
from host_runtime import SuspendableRLock


def make_daemon():
    daemon = deck.Daemon(types.SimpleNamespace(profiles=str(ROOT / 'host/profiles.default.json'), port='TEST',
                                               verbose=False, no_focus=True, deck_only=True))
    daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
    return daemon


def slow_button(daemon, actions):
    page = daemon.config['profiles']['main']['pages']['main']
    button = next(b for b in page if b['id'] == 1)
    button['actions'] = actions
    daemon.profile, daemon.page = 'main', 'main'
    return button


class QueueTests(unittest.TestCase):
    def test_a_full_queue_rejects_loudly_and_is_counted(self):
        daemon = make_daemon()
        for index in range(deck.JOB_QUEUE_SIZE):
            daemon.submit(('var', f'v{index}', '1'))
        with self.assertRaises(Busy):
            daemon.submit(('var', 'late', '1'))
        self.assertFalse(daemon.enqueue(('var', 'later', '1')))
        self.assertEqual(daemon.dropped_jobs, 2)
        self.assertEqual(daemon.jobs.qsize(), deck.JOB_QUEUE_SIZE)

    def test_multi_job_submit_is_all_or_nothing(self):
        daemon = make_daemon()
        for index in range(deck.JOB_QUEUE_SIZE - 2):
            daemon.submit(('var', f'v{index}', '1'))
        with self.assertRaises(Busy):
            daemon.submit(('wake',), ('profile', 'main'), ('page', 'main'))
        self.assertEqual(daemon.jobs.qsize(), deck.JOB_QUEUE_SIZE - 2)

    def test_queued_presses_from_before_a_reconnect_are_dropped_but_other_jobs_survive(self):
        daemon = make_daemon()
        daemon.submit(('press', 1, None, False, time.monotonic()), ('var', 'keep', '1'), ('api-press', 2))
        daemon.drop_queued_presses()
        self.assertEqual(daemon.jobs.get_nowait()[0], 'var')
        self.assertTrue(daemon.jobs.empty())

    def test_stale_presses_are_dropped_instead_of_replayed(self):
        daemon = make_daemon()
        daemon.start_press = Mock()
        daemon.handle_job(('press', 1, None, False, time.monotonic() - deck.STALE_PRESS_SECONDS - 1))
        daemon.start_press.assert_not_called()
        self.assertEqual(daemon.dropped_jobs, 1)

    def test_panel_jobs_are_dropped_while_disconnected_but_state_jobs_still_run(self):
        daemon = make_daemon()
        daemon.panel = None
        daemon.submit(('press', 1, None, False, time.monotonic()), ('var', 'who', 'Ada'))
        worker = threading.Thread(target=daemon.worker_loop, daemon=True)
        worker.start()
        daemon.jobs.join()
        daemon.stop.set()
        worker.join(2)
        self.assertEqual(daemon.custom_vars['who'], 'Ada')
        self.assertEqual(daemon.dropped_jobs, 1)


class SlowLaneTests(unittest.TestCase):
    def test_a_waiting_button_does_not_block_other_work_and_ignores_a_second_press(self):
        daemon = make_daemon()
        started, release = threading.Event(), threading.Event()

        def blocked(command, timeout, stop):
            started.set()
            release.wait(5)

        slow_button(daemon, [{'type': 'shell', 'command': 'long'}])
        with patch.object(deck, 'run_command', blocked):
            self.assertTrue(daemon.start_press(1))
            self.assertTrue(started.wait(2))
            # the state lock is free while the command waits, so other jobs run
            self.assertTrue(daemon.state_lock.acquire(timeout=1))
            daemon.state_lock.release()
            self.assertFalse(daemon.start_press(1), 'a running button must not run twice')
            daemon.panel.feedback.assert_called_with(1, False)
            release.set()
            for _ in range(100):
                if not daemon.slow_running:
                    break
                time.sleep(0.02)
        self.assertEqual(daemon.slow_running, set())
        self.assertTrue(daemon.last_action['ok'])

    def test_slow_lane_is_bounded(self):
        daemon = make_daemon()
        gate = threading.Event()
        daemon.profile, daemon.page = 'main', 'main'
        page = daemon.config['profiles']['main']['pages']['main']
        for button in page[:deck.SLOW_LANE_LIMIT + 1]:
            button['actions'] = [{'type': 'delay', 'ms': 1000}]
        ids = [b['id'] for b in page[:deck.SLOW_LANE_LIMIT + 1]]
        with patch.object(daemon.stop, 'wait', lambda seconds: gate.wait(5)):
            results = [daemon.start_press(i) for i in ids]
            gate.set()
        self.assertEqual(results, [True] * deck.SLOW_LANE_LIMIT + [False])


class CommandTests(unittest.TestCase):
    def test_a_hanging_command_is_killed_at_the_timeout(self):
        started = time.monotonic()
        with self.assertRaises(CommandFailed) as raised:
            run_command(f'"{sys.executable}" -c "import time; time.sleep(30)"', 0.6, threading.Event())
        self.assertLess(time.monotonic() - started, 5)
        self.assertIn('did not finish', str(raised.exception))

    def test_a_failing_command_reports_its_exit_code_and_stderr(self):
        command = f'"{sys.executable}" -c "import sys; sys.stderr.write(\'boom\'); sys.exit(3)"'
        with self.assertRaises(CommandFailed) as raised:
            run_command(command, 5, threading.Event())
        self.assertIn('code 3', str(raised.exception))
        self.assertIn('boom', str(raised.exception))

    def test_shutdown_cancels_a_running_command(self):
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        started = time.monotonic()
        with self.assertRaises(CommandFailed):
            run_command(f'"{sys.executable}" -c "import time; time.sleep(30)"', 30, stop)
        self.assertLess(time.monotonic() - started, 5)

    def test_a_successful_command_returns_quietly(self):
        run_command(f'"{sys.executable}" -c "pass"', 5, threading.Event())


class LockTests(unittest.TestCase):
    def test_suspended_lets_another_thread_in_and_restores_every_level(self):
        lock = SuspendableRLock()
        taken = []

        def other():
            with lock:
                taken.append(True)

        with lock:
            with lock:
                with lock.suspended():
                    thread = threading.Thread(target=other)
                    thread.start()
                    thread.join(2)
                self.assertEqual(taken, [True])
                self.assertEqual(lock._count, 2)
            self.assertEqual(lock._count, 1)
        self.assertIsNone(lock._owner)

    def test_releasing_a_lock_the_thread_does_not_hold_fails(self):
        with self.assertRaises(RuntimeError):
            SuspendableRLock().release()


class ConcurrencyTests(unittest.TestCase):
    def test_many_threads_submitting_while_the_worker_runs_lose_nothing_and_never_deadlock(self):
        daemon = make_daemon()
        worker = threading.Thread(target=daemon.worker_loop, daemon=True)
        worker.start()

        def hammer(number):
            for index in range(50):
                try:
                    daemon.submit(('var', f't{number}-{index}', '1'))
                except Busy:
                    time.sleep(0.001)

        threads = [threading.Thread(target=hammer, args=(number,)) for number in range(8)]
        started = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
        deadline = time.monotonic() + 15
        while daemon.jobs.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        daemon.stop.set()
        worker.join(2)
        self.assertFalse(any(thread.is_alive() for thread in threads), 'a submitting thread is stuck')
        self.assertEqual(daemon.jobs.unfinished_tasks, 0, 'queued jobs were not all handled')
        self.assertEqual(len(daemon.custom_vars) + daemon.dropped_jobs, 400,
                         'every request was either run or counted as rejected')
        self.assertLess(time.monotonic() - started, 20)


if __name__ == '__main__':
    unittest.main()
