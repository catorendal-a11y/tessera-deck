"""USB reconnects wait a little longer after each failure and log an outage once, not every attempt."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
from tesserad import ReconnectBackoff


class BackoffTests(unittest.TestCase):
    def test_the_wait_grows_to_a_ceiling_and_resets_after_a_success(self):
        backoff = ReconnectBackoff()
        self.assertEqual([backoff.failed('x')[0] for _ in range(6)], [2, 5, 10, 10, 10, 10])
        self.assertEqual(backoff.recovered(), 6)
        self.assertEqual(backoff.failed('x')[0], 2)

    def test_an_unchanged_problem_is_logged_again_only_when_the_wait_changes(self):
        backoff = ReconnectBackoff()
        logged = [backoff.failed('could not open COM4')[1] for _ in range(6)]
        self.assertEqual(logged, [True, True, True, False, False, False])

    def test_a_different_problem_is_always_logged(self):
        backoff = ReconnectBackoff()
        for _ in range(5):
            backoff.failed('could not open COM4')
        self.assertTrue(backoff.failed('another board answered')[1])

    def test_recovering_without_failures_reports_zero(self):
        self.assertEqual(ReconnectBackoff().recovered(), 0)


class ClosedPortTests(unittest.TestCase):
    """pyserial raises odd errors when the port is closed under a reading thread; none may escape or hang the host."""

    def daemon(self):
        import types
        from unittest.mock import Mock
        import tesserad as deck
        root = Path(__file__).resolve().parents[1]
        daemon = deck.Daemon(types.SimpleNamespace(profiles=str(root / 'host/profiles.default.json'), port='TEST',
                                                   verbose=False, no_focus=True, deck_only=True))
        daemon.log, daemon.publish_runtime = Mock(), Mock()
        return daemon

    def test_errors_from_a_port_closed_during_a_read_end_the_reader_quietly(self):
        from unittest.mock import Mock
        errors = (AttributeError("'NoneType' object has no attribute 'hEvent'"),
                  TypeError('byref() argument 1 must be _ctypes._CData, not None'),
                  OSError(6, 'The handle is invalid.'), ValueError('read of closed file'))
        for error in errors:
            with self.subTest(type(error).__name__):
                daemon = self.daemon()
                panel = Mock()
                panel.read_lines.side_effect = error
                daemon.panel = panel
                daemon.reader_loop(panel)
                self.assertTrue(daemon.connection_failed.is_set())
                daemon.publish_runtime.assert_called()

    def test_the_heartbeat_thread_also_ends_quietly_when_the_port_goes_away(self):
        from unittest.mock import Mock
        for error in (TypeError('byref() argument 1 must be _ctypes._CData, not None'), AttributeError('hEvent'),
                      OSError(6, 'The handle is invalid.')):
            with self.subTest(type(error).__name__):
                daemon = self.daemon()
                panel = Mock()
                daemon.panel = panel
                daemon.heartbeat = Mock(side_effect=error)
                daemon.heartbeat_loop(panel)


class LayoutAcknowledgeTests(unittest.TestCase):
    def panel(self, answers_after):
        """A PanelSerial without a port whose panel answers the layout only from the given attempt on."""
        import threading
        from unittest.mock import Mock
        import tesserad as deck
        panel = deck.PanelSerial.__new__(deck.PanelSerial)
        panel.log, panel.write_lock = Mock(), threading.RLock()
        panel.cfg_done, panel.cfg_reply = threading.Event(), ''
        panel.ack_seconds, panel.attempts = 0.02, 0
        sent = []

        def send_line(text):
            sent.append(text)
            if text == 'AD_CFG_END':
                panel.attempts += 1
                if panel.attempts >= answers_after:
                    panel.cfg_reply = 'AD_CFG_END OK 1'
                    panel.cfg_done.set()
        panel.send_line = send_line
        panel.sent = sent
        return panel

    def test_a_missing_answer_is_retried_once_before_giving_up(self):
        panel = self.panel(answers_after=2)
        panel.push_buttons([{'id': 1, 'label': 'A'}])
        self.assertEqual(panel.attempts, 2)
        self.assertEqual(panel.sent.count('AD_CFG_BEGIN'), 2)

    def test_two_missing_answers_still_report_a_timeout(self):
        panel = self.panel(answers_after=99)
        with self.assertRaises(TimeoutError):
            panel.push_buttons([{'id': 1, 'label': 'A'}])
        self.assertEqual(panel.attempts, 2)

    def test_a_refusal_is_not_retried(self):
        panel = self.panel(answers_after=1)
        send = panel.send_line

        def refuse(text):
            send(text)
            if text == 'AD_CFG_END':
                panel.cfg_reply = 'AD_CFG_END INVALID'
        panel.send_line = refuse
        with self.assertRaises(ValueError):
            panel.push_buttons([{'id': 1, 'label': 'A'}])
        self.assertEqual(panel.attempts, 1)


if __name__ == '__main__':
    unittest.main()
