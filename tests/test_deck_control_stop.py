"""Stopping the host for a firmware install: a host that has ended counts as stopped even when its parent (the tray) has not
collected it yet, and the tray collects the hosts it started."""
import subprocess
import sys
import time
import unittest
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import deck_control  # noqa: E402

PARENT = ("import subprocess, sys, time\n"
          "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
          "print(child.pid, flush=True)\n"
          "time.sleep(60)\n")  # never waits for the child: it stays a zombie once it ends


@unittest.skipIf(sys.platform == 'win32', 'a zombie is a POSIX state')
class ZombieTests(unittest.TestCase):
    def setUp(self):
        self.parent = subprocess.Popen([sys.executable, '-c', PARENT], stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (self.parent.kill(), self.parent.wait(), self.parent.stdout.close()))
        self.child = psutil.Process(int(self.parent.stdout.readline()))

    def test_a_host_that_ended_but_was_not_collected_counts_as_stopped(self):
        self.assertTrue(deck_control.is_alive(self.child))
        self.child.terminate()
        deadline = time.monotonic() + 5
        while self.child.status() != psutil.STATUS_ZOMBIE and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.child.status(), psutil.STATUS_ZOMBIE)
        self.assertTrue(self.child.is_running(), 'psutil still sees it, which is why its own wait never returned')
        self.assertFalse(deck_control.is_alive(self.child))
        started = time.monotonic()
        self.assertEqual(deck_control.wait_until_gone([self.child], 8), [])
        self.assertLess(time.monotonic() - started, 1)

    def test_a_host_that_still_runs_is_reported_after_the_time_is_up(self):
        started = time.monotonic()
        self.assertEqual(deck_control.wait_until_gone([self.child], 0.3), [self.child])
        self.assertGreaterEqual(time.monotonic() - started, 0.3)


class ControllerTests(unittest.TestCase):
    def test_a_host_the_controller_started_is_collected_when_it_ends(self):
        controller = deck_control.Controller()
        controller.pid_path = controller.runtime_path = Path('/nonexistent/none.json')
        process = subprocess.Popen([sys.executable, '-c', 'pass'])
        self.addCleanup(process.wait)
        controller.children.append(process)
        deadline = time.monotonic() + 5
        while controller.children and time.monotonic() < deadline:
            controller.processes()
            time.sleep(0.05)
        self.assertEqual(controller.children, [])
        self.assertIsNotNone(process.returncode)


if __name__ == '__main__':
    unittest.main()
