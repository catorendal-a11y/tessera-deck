"""Linux session pieces: the screen lock state, and that a timed-out command takes its children with it."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_marks import linux_only_module
linux_only_module(__name__)
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import action_runner
from platform_linux import session


def asking(answers):
    """A fake `run` that answers by the program and the screensaver service in the command."""
    calls = []

    def run(args):
        calls.append(args)
        text = ' '.join(args)
        for key, value in answers.items():
            if key in text:
                return value
        return ''
    run.calls = calls
    return run


class LockTests(unittest.TestCase):
    def setUp(self):
        session._cache = (0.0, False)

    def test_logind_locked_hint_means_locked(self):
        self.assertTrue(session.locked(run=asking({'loginctl': 'yes\n'})))

    def test_a_desktop_screensaver_that_is_active_means_locked(self):
        run = asking({'loginctl': 'no\n', 'ListNames': "(['org.cinnamon.ScreenSaver', ':1.5'],)", 'org.cinnamon.ScreenSaver.GetActive': '(true,)\n'})
        self.assertTrue(session.locked(run=run))

    def test_nothing_locked_and_missing_tools_count_as_unlocked(self):
        self.assertFalse(session.locked(run=asking({'loginctl': 'no\n', 'ListNames': "(['org.cinnamon.ScreenSaver'],)",
                                                    'GetActive': '(false,)\n'})))
        session._cache = (0.0, False)
        self.assertFalse(session.locked(run=asking({})))

    def test_the_answer_is_kept_for_a_moment(self):
        run = asking({'loginctl': 'yes\n'})
        clock = [100.0]
        session.locked(now=lambda: clock[0], run=run)
        asked = len(run.calls)
        clock[0] += 1.0
        self.assertTrue(session.locked(now=lambda: clock[0], run=run))
        self.assertEqual(len(run.calls), asked)
        clock[0] += 2.0
        session.locked(now=lambda: clock[0], run=run)
        self.assertGreater(len(run.calls), asked)


@unittest.skipUnless(os.name == 'posix', 'POSIX only')
class CommandTreeTests(unittest.TestCase):
    def test_a_command_that_times_out_is_killed_with_everything_it_started(self):
        with tempfile.TemporaryDirectory() as folder:
            pid_file = Path(folder, 'child.pid')
            command = f'sleep 30 & echo $! > {pid_file}; wait'
            with self.assertRaises(action_runner.CommandFailed):
                action_runner.run_command(command, 0.6, threading.Event())
            child = int(pid_file.read_text())
            time.sleep(0.3)
            with self.assertRaises(ProcessLookupError):
                os.kill(child, 0)


if __name__ == '__main__':
    unittest.main()


class FakeLink:
    """Just enough of a pyserial port for PanelSerial.verify and push_buttons."""

    def __init__(self, port, answer_after=0):
        self.port, self.sent, self.queue, self.answer_after = port, [], [], answer_after

    def reset_input_buffer(self):
        self.queue.clear()

    def write(self, raw):
        self.sent.append(raw)
        if len(self.sent) > self.answer_after:
            self.queue.append(b'{"type":"info","boardId":"tessera-p4-crowpanel7","protocol":4}\n')
        return len(raw)

    in_waiting = property(lambda self: len(self.queue[0]) if self.queue else 0)

    def read(self, size):
        return self.queue.pop(0) if self.queue else b''

    def close(self):
        pass


class ResetOnOpenTests(unittest.TestCase):
    def link(self, port, answer_after=0):
        import panel_serial
        panel = panel_serial.PanelSerial.__new__(panel_serial.PanelSerial)
        panel.ser, panel.rx, panel.write_lock, panel.log = FakeLink(port, answer_after), bytearray(), threading.RLock(), lambda *a: None
        return panel

    def test_a_dev_port_waits_for_the_restart_asks_again_and_settles_afterwards(self):
        import panel_serial
        from unittest.mock import patch
        panel = self.link('/dev/ttyUSB1', answer_after=2)
        slept = []
        with patch.object(panel_serial, 'ASK_AGAIN_SECONDS', 0.0), patch.object(panel_serial.time, 'sleep', slept.append):
            panel.verify()
        self.assertGreaterEqual(len(panel.ser.sent), 3)  # asked again until it answered
        self.assertIn(panel_serial.SETTLE_AFTER_RESET_SECONDS, slept)
        self.assertEqual(panel.info['boardId'], 'tessera-p4-crowpanel7')

    def test_other_ports_ask_once_and_do_not_wait(self):
        import panel_serial
        from unittest.mock import patch
        panel = self.link('COM4')
        slept = []
        with patch.object(panel_serial.time, 'sleep', slept.append):
            panel.verify()
        self.assertEqual(len(panel.ser.sent), 1)
        self.assertEqual(slept, [])

    def test_a_damaged_layout_is_sent_again_on_the_same_dev_port_only(self):
        for port, tries in (('/dev/ttyUSB1', 2), ('COM4', 1)):
            panel = self.link(port)
            calls = []

            def push(payload, calls=calls):
                calls.append(payload)
                if len(calls) == 1:
                    raise ValueError('AD_CFG_END INVALID')
            panel.push_payload = push
            try:
                panel.push_buttons([{'id': 1, 'label': 'A'}])
            except ValueError:
                pass
            self.assertEqual(len(calls), tries, port)


class NotifyTests(unittest.TestCase):
    def test_a_notification_goes_to_notify_send_with_the_title_and_text(self):
        from platform_linux import notify
        from unittest.mock import Mock, patch
        run = Mock(return_value=Mock(returncode=0))
        with patch('shutil.which', return_value='/usr/bin/notify-send'):
            self.assertTrue(notify.notify('Panel connected', 'Tessera', run=run))
        self.assertEqual(run.call_args.args[0], ['notify-send', '--app-name=Tessera', '--', 'Tessera', 'Panel connected'])

    def test_without_notify_send_nothing_happens_and_nothing_raises(self):
        from platform_linux import notify
        from unittest.mock import patch
        with patch('shutil.which', return_value=None):
            self.assertFalse(notify.notify('x'))


@unittest.skipUnless(os.name == 'posix', 'POSIX only')
class StopEditorTests(unittest.TestCase):
    """The tray's Quit stops an editor that runs in a browser tab, and only that process."""

    def setUp(self):
        import json
        import subprocess
        import psutil
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.script = Path(self.folder.name, 'tessera_app.py')
        # the editor: it exits on SIGINT like the real one, and removes its record on the way out
        self.record = Path(self.folder.name, 'editor.local.json')
        self.script.write_text('import time\ntry:\n    time.sleep(60)\nexcept KeyboardInterrupt:\n    pass\n')
        self.process = subprocess.Popen([sys.executable, str(self.script)])
        self.addCleanup(lambda: self.process.poll() is None and self.process.kill())
        time.sleep(0.4)
        self.created = psutil.Process(self.process.pid).create_time()
        self.write = lambda **extra: self.record.write_text(json.dumps(dict(pid=self.process.pid, created=self.created, **extra)))

    def stop(self):
        import deck_control
        return deck_control.stop_editor(self.record, self.script, wait=3)

    def test_an_editor_in_a_browser_tab_is_stopped(self):
        self.write(browser=True)
        self.assertTrue(self.stop())
        self.assertIsNotNone(self.process.wait(3))

    def test_an_editor_with_its_own_window_is_left_alone(self):
        self.write()
        self.assertFalse(self.stop())
        self.assertIsNone(self.process.poll())

    def test_a_record_that_names_another_process_or_a_reused_pid_touches_nothing(self):
        self.write(browser=True)
        import json
        stale = json.loads(self.record.read_text())
        self.record.write_text(json.dumps(dict(stale, created=stale['created'] - 100)))  # same pid, another start time
        self.assertFalse(self.stop())
        self.record.write_text(json.dumps(dict(stale, pid=os.getpid())))  # a live process that is not the editor
        self.assertFalse(self.stop())
        self.assertIsNone(self.process.poll())

    def test_no_record_or_a_broken_one_is_not_an_error(self):
        self.assertFalse(self.stop())
        self.record.write_text('not json')
        self.assertFalse(self.stop())
