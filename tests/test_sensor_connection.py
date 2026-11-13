import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import psutil
import tesserad as deck
import host_support  # noqa: E402
import win_input
from sensor_sources import LibreHardwareMonitorReader

TREE = {'Text': 'root', 'Children': [{'Text': 'pc', 'Children': [{'Text': 'CPU', 'Children': [
    {'Text': 'Core', 'SensorId': '/amdcpu/0/temperature/0', 'Value': '45.0 °C'}]}]}]}


class Sensors(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_GET(self):
        self.server.requests += 1
        body = json.dumps(TREE).encode() if self.server.status == 200 else b'no'
        self.send_response(self.server.status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        if self.server.close_after_reply:
            self.close_connection = True

    def setup(self):
        super().setup()
        self.server.connections += 1

    def log_message(self, *_):
        pass


class SensorConnectionTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Sensors)
        self.server.requests = self.server.connections = 0
        self.server.status, self.server.close_after_reply = 200, False
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.reader = LibreHardwareMonitorReader(f'http://127.0.0.1:{self.server.server_port}/data.json', timeout=2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(lambda: self.reader._connection and self.reader._connection.close())

    def test_reads_share_one_connection(self):
        for _ in range(3):
            self.assertEqual(self.reader.read()[0]['value'], 45.0)
        self.assertEqual((self.server.requests, self.server.connections), (3, 1))

    def test_a_connection_closed_by_the_tool_is_not_an_outage(self):
        self.server.close_after_reply = True
        self.assertTrue(self.reader.read())
        self.assertTrue(self.reader.read())
        self.assertEqual(self.reader._retry_at, 0.0)
        self.assertEqual(self.server.connections, 2)

    def test_an_error_reply_waits_before_trying_again(self):
        self.server.status = 500
        self.assertEqual(self.reader.read(), [])
        self.assertEqual(self.reader.read(), [])
        self.assertEqual(self.server.requests, 1)

    def test_no_server_reads_as_no_sensors(self):
        self.server.shutdown()
        self.server.server_close()
        self.addCleanup(lambda: None)
        reader = LibreHardwareMonitorReader('http://127.0.0.1:9/data.json', timeout=.2)
        self.assertEqual(reader.read(), [])


class ChildNameTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(win_input, '_child_names', (None, 0.0, []))
        patcher.start()
        self.addCleanup(patcher.stop)
        child = Mock()
        child.name.return_value = 'Claude.exe'
        self.process = patch.object(psutil, 'Process', return_value=Mock(children=Mock(return_value=[child])))
        self.listed = self.process.start()
        self.addCleanup(self.process.stop)

    def test_the_same_window_is_not_listed_again_at_once(self):
        self.assertEqual(deck.child_names(10), ['claude.exe'])
        self.assertEqual(deck.child_names(10), ['claude.exe'])
        self.assertEqual(self.listed.call_count, 1)

    def test_a_new_window_is_listed_at_once(self):
        deck.child_names(10)
        deck.child_names(11)
        self.assertEqual(self.listed.call_count, 2)

    def test_the_list_refreshes_after_a_few_seconds(self):
        with patch.object(deck.time, 'monotonic', side_effect=[100.0, 100.0 + deck.CHILD_NAMES_SECONDS]):
            deck.child_names(10)
            deck.child_names(10)
        self.assertEqual(self.listed.call_count, 2)


class ProfileLockColorTests(unittest.TestCase):
    def color(self, button_key):
        daemon = host_support.test_daemon(port='TEST', no_focus=True)
        daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
        daemon.config['profiles'][daemon.profile]['pages'][daemon.page] = [
            {'id': 1, 'label': 'Lock', 'icon': 'ok', 'color': '#35D07F', button_key: [{'type': 'profile_lock'}]}]
        daemon.profile_locked = True
        return next(item for item in daemon.current_buttons() if item['id'] == 1)['color']

    def test_the_lock_key_is_orange_for_every_kind_of_press(self):
        for key in ('actions', 'hold_actions', 'double_actions'):
            with self.subTest(key=key):
                self.assertEqual(self.color(key), '#FFB13B')


if __name__ == '__main__':
    unittest.main()
