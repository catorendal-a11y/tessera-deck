"""Wi-Fi setup over USB (protocol 5): gating, exact bytes, replies, status parsing, scopes and password leak checks."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
import zipfile
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import host_support  # noqa: E402
import config_check  # noqa: E402
import diagnostics  # noqa: E402
import panel_serial  # noqa: E402
import plugins  # noqa: E402
from control_api import ControlServer  # noqa: E402

CANARY = 'Canary-Pass-9137'  # a made-up test password; it must never leave the serial write
SSID = 'HomeNet-7f3a'
IP = '192.168.77.41'
MAC = 'AA:BB:CC:DD:EE:42'


class FakeSerial:
    """A panel on a scripted port: answers get_info with `protocol`, and AD_WIFI_* lines with `answers`."""
    protocol = 5
    answers = {}

    def __init__(self):
        self.port, self.baudrate, self.timeout, self.write_timeout = None, 0, 0, 0
        self.dtr = self.rts = False
        self.written = bytearray()
        self.pending = bytearray()
        self.lock = threading.Lock()
        self.answers = dict(FakeSerial.answers)

    def open(self):
        pass

    def close(self):
        pass

    def reset_input_buffer(self):
        self.pending.clear()

    def flush(self):
        pass

    def write(self, raw):
        with self.lock:
            self.written.extend(raw)
            if b'get_info' in raw:
                info = {'type': 'info', 'boardId': 'tessera-p4', 'firmwareVersion': '9.9.9', 'bootId': 1, 'protocol': self.protocol}
                self.pending.extend((json.dumps(info) + '\n').encode())
            for command, answer in self.answers.items():
                if raw.startswith(command.encode()):
                    self.pending.extend(answer.encode())
        return len(raw)

    @property
    def in_waiting(self):
        return len(self.pending)

    def read(self, count):
        with self.lock:
            data, self.pending = bytes(self.pending[:count]), self.pending[count:]
        return data


def open_panel(protocol=5, answers=None):
    FakeSerial.protocol, FakeSerial.answers = protocol, answers or {}
    with patch.object(panel_serial, 'serial', types.SimpleNamespace(Serial=FakeSerial)), \
            patch.object(panel_serial, 'HANDSHAKE_SECONDS', 0.5):
        return panel_serial.PanelSerial('COM9', Mock())


def answer_in_background(panel, reply, delay=0.05):
    """What the daemon's reader loop does with an AD_WIFI_ answer, for a panel without a reader thread."""
    def run():
        time.sleep(delay)
        panel.wifi_reply = reply
        panel.wifi_done.set()
    threading.Thread(target=run, daemon=True).start()


class CredentialRules(unittest.TestCase):
    """The same table as the native wifi_config tests."""
    def test_valid_credentials(self):
        for ssid, password in ((SSID, ''), ('a' * 32, 'x' * 8), ('æ' * 16, 'y' * 63), ('Café 😀', 'ab' * 32),
                               ('net', ' !~' * 3), ('Hjem', 'F' * 64)):
            panel_serial.check_wifi_credentials(ssid, password)

    def test_invalid_ssid(self):
        for ssid in ('', 'a' * 33, 'æ' * 17, 'tab\there', 'bell\x07', 'del\x7f', None, 5, '\ud800'):
            with self.assertRaises(ValueError, msg=repr(ssid)) as raised:
                panel_serial.check_wifi_credentials(ssid, 'password1')
            self.assertTrue(str(raised.exception).startswith('ssid: '))

    def test_invalid_password_and_the_message_never_holds_it(self):
        for password in ('short77', 'x' * 64, 'g' * 64, 'x' * 65, 'pässwörd1', 'tab\tpassword', None, 12345678):
            with self.assertRaises(ValueError, msg=repr(password)) as raised:
                panel_serial.check_wifi_credentials(SSID, password)
            self.assertTrue(str(raised.exception).startswith('password: '))
            self.assertNotIn(str(password), str(raised.exception))

    def test_the_line_is_compact_ascii_json(self):
        self.assertEqual(panel_serial.wifi_line('Café', 'pass word"\\'),
                         'AD_WIFI_SET {"ssid":"Caf\\u00e9","password":"pass word\\"\\\\"}')
        line = panel_serial.wifi_line('😀' * 8, '~' * 63)
        self.assertTrue(line.isascii())
        self.assertLessEqual(len(line) + 1, 1099)
        self.assertEqual(json.loads(line.removeprefix('AD_WIFI_SET ')), {'ssid': '😀' * 8, 'password': '~' * 63})
        with self.assertRaises(ValueError):
            panel_serial.wifi_line(SSID, 'short')


class StatusParsing(unittest.TestCase):
    def test_a_connected_line(self):
        message = {'type': 'wifi', 'state': 'connected', 'ssid': SSID, 'ip': IP, 'rssi': -58, 'mac': MAC.lower(),
                   'cp': '2.7.0', 'password': CANARY, 'extra': 1}
        self.assertEqual(panel_serial.parse_wifi_status(message),
                         {'state': 'connected', 'ssid': SSID, 'ip': IP, 'rssi': -58, 'mac': MAC, 'cp': '2.7.0'})

    def test_fields_that_do_not_fit_the_state_or_type_are_dropped(self):
        self.assertEqual(panel_serial.parse_wifi_status({'type': 'wifi', 'state': 'failed', 'reason': 'auth', 'ssid': SSID,
                                                         'ip': IP, 'rssi': -40}),
                         {'state': 'failed', 'reason': 'auth', 'ssid': SSID})
        self.assertEqual(panel_serial.parse_wifi_status({'type': 'wifi', 'state': 'connected', 'ip': '999.1.1.1', 'rssi': '-5',
                                                         'reason': 'bogus', 'ssid': 7, 'mac': 'nope', 'cp': 'x' * 40}),
                         {'state': 'connected'})
        self.assertEqual(panel_serial.parse_wifi_status({'type': 'wifi', 'state': 'off'}), {'state': 'off'})

    def test_malformed_lines(self):
        for message in ({'type': 'wifi'}, {'type': 'wifi', 'state': 'sleeping'}, {'type': 'info', 'state': 'off'}, [], None):
            self.assertIsNone(panel_serial.parse_wifi_status(message), repr(message))


class PanelCommands(unittest.TestCase):
    def test_protocol_five_is_accepted_and_supports_wifi(self):
        panel = open_panel(5)
        self.assertEqual(panel.info['protocol'], 5)
        self.assertTrue(panel.supports_wifi())

    def test_older_firmware_gets_nothing_written(self):
        panel = open_panel(4)
        self.assertFalse(panel.supports_wifi())
        before = bytes(panel.ser.written)
        for call in (lambda: panel.wifi_set(SSID, CANARY), panel.wifi_clear, panel.wifi_status):
            with self.assertRaises(RuntimeError):
                call()
        self.assertEqual(bytes(panel.ser.written), before)

    def test_set_writes_the_exact_line_and_waits_for_ok(self):
        panel = open_panel(5)
        start = len(panel.ser.written)
        answer_in_background(panel, 'AD_WIFI_SET OK')
        panel.wifi_set(SSID, CANARY)
        self.assertEqual(bytes(panel.ser.written[start:]),
                         ('AD_WIFI_SET {"ssid":"%s","password":"%s"}\n' % (SSID, CANARY)).encode())

    def test_invalid_answer_raises_with_its_text(self):
        panel = open_panel(5)
        answer_in_background(panel, 'AD_WIFI_SET INVALID password')
        with self.assertRaises(OSError) as raised:
            panel.wifi_set(SSID, CANARY)
        self.assertEqual(str(raised.exception), 'AD_WIFI_SET INVALID password')

    def test_no_answer_times_out(self):
        panel = open_panel(5)
        with patch.object(panel_serial, 'WIFI_REPLY_SECONDS', 0.2), self.assertRaises(TimeoutError):
            panel.wifi_clear()

    def test_invalid_credentials_are_refused_before_anything_is_written(self):
        panel = open_panel(5)
        before = bytes(panel.ser.written)
        with self.assertRaises(ValueError):
            panel.wifi_set(SSID, 'short')
        self.assertEqual(bytes(panel.ser.written), before)

    def test_clear_and_status(self):
        panel = open_panel(5)
        start = len(panel.ser.written)
        answer_in_background(panel, 'AD_WIFI_CLEAR OK')
        panel.wifi_clear()
        panel.wifi_status()
        self.assertEqual(bytes(panel.ser.written[start:]), b'AD_WIFI_CLEAR\nAD_WIFI_STATUS\n')


class ConfigRules(unittest.TestCase):
    def config(self, wifi):
        config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        config['panel'] = dict(config.get('panel') or {}, wifi=wifi)
        return config

    def test_only_the_network_name_is_kept(self):
        config_check.validate_config(self.config({'ssid': SSID}))
        for wifi in ({'ssid': SSID, 'password': CANARY}, {}, {'ssid': ''}, {'ssid': 'a' * 33}, {'ssid': 'a\nb'},
                     {'ssid': 5}, 'HomeNet', None):
            with self.assertRaises(ValueError, msg=repr(wifi)) as raised:
                config_check.validate_config(self.config(wifi))
            self.assertIn('panel.wifi.ssid', str(raised.exception))
            self.assertNotIn(CANARY, str(raised.exception))


class ControlApiRoute(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.daemon = Mock()
        self.daemon.events = plugins.EventLog()
        self.daemon.connection_failed = threading.Event()
        self.daemon.wifi = {'state': 'connecting', 'ssid': SSID}
        self.daemon.panel = Mock()
        self.daemon.panel.supports_wifi.return_value = True
        self.logged = []
        self.daemon.log = self.logged.append
        self.api = ControlServer(self.daemon, Path(temp.name) / 'api.json')
        self.api.start()
        self.addCleanup(self.api.stop)

    def call(self, data, token=None):
        request = urllib.request.Request(f'http://127.0.0.1:{self.api.server.server_port}/v1/wifi', method='POST',
                                         data=json.dumps(data).encode(),
                                         headers={'Content-Type': 'application/json', 'X-Deck-Token': token or self.api.token})
        try:
            with urllib.request.urlopen(request, timeout=3) as reply:
                return reply.status, json.loads(reply.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_the_owner_sets_clears_and_reads(self):
        self.assertEqual(self.call({'do': 'set', 'ssid': SSID, 'password': CANARY}),
                         (200, {'wifi': {'state': 'connecting', 'ssid': SSID}}))
        self.daemon.panel.wifi_set.assert_called_once_with(SSID, CANARY)
        self.assertEqual(self.call({'do': 'clear'})[0], 200)
        self.daemon.panel.wifi_clear.assert_called_once_with()
        self.assertEqual(self.call({'do': 'status'})[0], 200)
        self.daemon.panel.wifi_status.assert_called_once_with()
        self.daemon.submit.assert_not_called()  # never through the job queue
        self.assertFalse(any(CANARY in line or SSID in line for line in self.logged), self.logged)
        self.assertIn('API owner POST /v1/wifi -> 200', self.logged)

    def test_a_plugin_is_refused_even_when_its_grant_lists_wifi(self):
        token = self.api.add_grant('sneaky', ['var', 'wifi'])
        self.assertEqual(self.call({'do': 'set', 'ssid': SSID, 'password': CANARY}, token)[0], 403)
        self.daemon.panel.wifi_set.assert_not_called()

    def test_no_panel_or_old_firmware_is_a_conflict(self):
        self.daemon.panel.supports_wifi.return_value = False
        self.assertEqual(self.call({'do': 'status'}),
                         (409, {'error': 'The panel firmware does not support Wi-Fi; update it'}))
        self.daemon.panel = None
        self.assertEqual(self.call({'do': 'status'}), (409, {'error': 'The panel is not connected'}))

    def test_bad_input_and_panel_refusals(self):
        self.daemon.panel.wifi_set.side_effect = lambda ssid, password: panel_serial.check_wifi_credentials(ssid, password)
        code, body = self.call({'do': 'set', 'ssid': SSID, 'password': 'short'})
        self.assertEqual(code, 400)
        self.assertTrue(body['error'].startswith('password: '))
        self.assertEqual(self.call({'do': 'set', 'ssid': '', 'password': CANARY})[1]['error'][:6], 'ssid: ')
        self.assertEqual(self.call({'do': 'reboot'})[0], 400)
        self.daemon.panel.wifi_set.side_effect = OSError('AD_WIFI_SET FAILED storage')
        code, body = self.call({'do': 'set', 'ssid': SSID, 'password': CANARY})
        self.assertEqual(code, 409)
        self.assertIn('FAILED storage', body['error'])
        self.assertNotIn(CANARY, body['error'])


class EditorCommand(unittest.TestCase):
    def test_panel_wifi_posts_to_the_host_and_writes_no_file(self):
        import tessera_app
        import deckctl
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        shutil.copyfile(ROOT / 'host/profiles.default.json', folder / 'profiles.json')
        editor = tessera_app.Editor(folder / 'profiles.json', dashboard=lambda: {'running': True, 'device': {}})
        before = {path: path.stat().st_mtime_ns for path in folder.iterdir()}
        info = {'pid': 1, 'port': 2, 'token': 't'}
        with patch.object(deckctl, 'load_info', return_value=info) as load, \
                patch.object(deckctl, 'call', return_value={'wifi': {'state': 'connecting'}}) as call:
            self.assertEqual(editor.command('panel-wifi', {'do': 'set', 'ssid': SSID, 'password': CANARY}),
                             {'wifi': {'state': 'connecting'}})
        load.assert_called_once_with(folder / 'deck-api.local.json')
        self.assertEqual(call.call_args.args[:3], (info, 'POST', '/v1/wifi'))
        self.assertEqual({path: path.stat().st_mtime_ns for path in folder.iterdir()}, before)
        for path in [*folder.iterdir(), ROOT / 'host/deck-command.local.json']:
            if path.is_file():
                self.assertNotIn(CANARY, path.read_text(encoding='utf-8', errors='replace'), path)

    def test_errors_from_the_host_are_plain_messages(self):
        import tessera_app
        import deckctl
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        shutil.copyfile(ROOT / 'host/profiles.default.json', folder / 'profiles.json')
        editor = tessera_app.Editor(folder / 'profiles.json', dashboard=lambda: {})
        with patch.object(deckctl, 'load_info', side_effect=deckctl.DeckctlError('The Tessera host is not running')):
            with self.assertRaisesRegex(ValueError, 'not running'):
                editor.command('panel-wifi', {'do': 'status'})
        with self.assertRaises(ValueError):
            editor.command('panel-wifi', {'do': 'set', 'ssid': SSID, 'password': 'short'})
        with self.assertRaises(ValueError):
            editor.command('panel-wifi', {'do': 'erase'})


class PasswordNeverLeaks(unittest.TestCase):
    """A full set through the control API and the daemon's reader loop: the canary reaches only the serial port."""
    def test_canary(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        profiles = folder / 'profiles.json'
        shutil.copyfile(ROOT / 'host/profiles.default.json', profiles)
        daemon = host_support.test_daemon(profiles)
        daemon.args.verbose = True  # the most the host ever logs
        status = {'type': 'wifi', 'state': 'connected', 'ssid': SSID, 'ip': IP, 'rssi': -50, 'mac': MAC, 'cp': '2.7.0'}
        panel = open_panel(5, {'AD_WIFI_SET ': 'AD_WIFI_SET OK\n' + json.dumps(status) + '\n'})
        daemon.panel, daemon.device_info = panel, dict(panel.info)
        output = io.StringIO()
        api = ControlServer(daemon, folder / 'deck-api.local.json')
        api.start()
        self.addCleanup(api.stop)
        reader = threading.Thread(target=daemon.reader_loop, args=(panel,), daemon=True)
        with contextlib.redirect_stdout(output):
            reader.start()
            request = urllib.request.Request(f'http://127.0.0.1:{api.server.server_port}/v1/wifi', method='POST',
                                             data=json.dumps({'do': 'set', 'ssid': SSID, 'password': CANARY}).encode(),
                                             headers={'Content-Type': 'application/json', 'X-Deck-Token': api.token})
            with urllib.request.urlopen(request, timeout=8) as reply:
                self.assertEqual(reply.status, 200)
            for _ in range(50):
                if daemon.wifi:
                    break
                time.sleep(0.02)
            daemon.publish_runtime(True, force=True)
            daemon.stop.set()
            reader.join(2)
        self.assertIn(CANARY.encode(), bytes(panel.ser.written))  # it did reach the panel
        self.assertEqual(daemon.wifi, {key: value for key, value in status.items() if key != 'type'})
        runtime = json.loads((folder / 'deck-runtime.local.json').read_text(encoding='utf-8'))
        self.assertEqual(runtime['wifi']['state'], 'connected')
        log = output.getvalue()
        self.assertIn('API owner POST /v1/wifi -> 200', log)
        dashboard = {'running': True, 'device': {'connected': True, 'wifi': runtime['wifi']}}
        bundle = diagnostics.build(folder / 'diag', json.loads(profiles.read_text(encoding='utf-8')), dashboard, '1.0',
                                   folder / 'missing.log')
        with zipfile.ZipFile(bundle) as archive:
            report = archive.read('report.json').decode('utf-8')
        self.assertIn('"state": "connected"', report)
        for text, where in ((log, 'log'), ((folder / 'deck-runtime.local.json').read_text(encoding='utf-8'), 'runtime'),
                            (profiles.read_text(encoding='utf-8'), 'profiles'), (report, 'diagnostics')):
            self.assertNotIn(CANARY, text, where)
        for secret in (SSID, IP, MAC):
            self.assertNotIn(secret, report)


class ApiKeyNeverLogged(unittest.TestCase):
    """The panel's AD_API_KEY answer reaches panel.api_key_reply only, never the verbose log or the runtime file."""
    def test_canary(self):
        key = 'Q2FuYXJ5LUFwaS1LZXktMzItYnl0ZXMtMTIzNDU2Nzg='  # a made-up 32-byte test key
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        profiles = folder / 'profiles.json'
        shutil.copyfile(ROOT / 'host/profiles.default.json', profiles)
        daemon = host_support.test_daemon(profiles)
        daemon.args.verbose = True
        panel = open_panel(5, {'AD_API_KEY': f'AD_API_KEY {key}\nother line\n'})
        daemon.panel, daemon.device_info = panel, dict(panel.info)
        output = io.StringIO()
        reader = threading.Thread(target=daemon.reader_loop, args=(panel,), daemon=True)
        with contextlib.redirect_stdout(output):
            reader.start()
            panel.send_line('AD_API_KEY')
            self.assertTrue(panel.api_key_done.wait(3))
            time.sleep(0.2)
            daemon.publish_runtime(True, force=True)
            daemon.stop.set()
            reader.join(2)
        self.assertEqual(panel_serial.parse_api_key(panel.api_key_reply), key)
        log = output.getvalue()
        self.assertIn('Panel: other line', log)  # the verbose log was on
        runtime = (folder / 'deck-runtime.local.json').read_text(encoding='utf-8')
        for text, where in ((log, 'log'), (runtime, 'runtime')):
            self.assertNotIn(key, text, where)


if __name__ == '__main__':
    unittest.main()
