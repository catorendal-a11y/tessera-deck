"""Device identity and protocol handshake with a scripted serial port; no hardware."""
import hashlib
import json
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import panel_serial
import tesserad as deck
import host_support  # noqa: E402
from host_runtime import candidate_ports


def info(**fields):
    base = {'type': 'info', 'boardId': 'tessera-p4', 'firmwareVersion': '1.2.3', 'bootId': 7}
    return (json.dumps(dict(base, **fields)) + '\n').encode()


class FakeSerial:
    """Answers get_info with the scripted bytes; remembers whether it was closed."""
    script = b''
    opened = []

    def __init__(self):
        self.port, self.baudrate, self.timeout, self.write_timeout = None, 0, 0, 0
        self.dtr = self.rts = False
        self.written = bytearray()
        self.pending = bytearray()
        self.closed = False
        FakeSerial.opened.append(self)

    def open(self):
        pass

    def close(self):
        self.closed = True

    def reset_input_buffer(self):
        self.pending.clear()

    def write(self, raw):
        self.written.extend(raw)
        if b'get_info' in raw:
            self.pending.extend(self.script)
        return len(raw)

    @property
    def in_waiting(self):
        return len(self.pending)

    def read(self, count):
        data, self.pending = bytes(self.pending[:count]), self.pending[count:]
        return data


def panel(port, script):
    FakeSerial.script = script
    with patch.object(panel_serial, 'serial', types.SimpleNamespace(Serial=FakeSerial)):
        return deck.PanelSerial(port, Mock())


class HandshakeTests(unittest.TestCase):
    def setUp(self):
        FakeSerial.opened = []
        patcher = patch.object(panel_serial, 'HANDSHAKE_SECONDS', 0.3)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_tessera_panel_is_accepted_and_its_protocol_recorded(self):
        connected = panel('COM4', info(protocol=2))
        self.assertEqual((connected.info['firmwareVersion'], connected.info['protocol']), ('1.2.3', 2))
        self.assertFalse(FakeSerial.opened[0].closed)

    def test_firmware_without_a_protocol_field_counts_as_protocol_one(self):
        self.assertEqual(panel('COM4', info()).info['protocol'], 1)

    def test_early_key_events_from_an_older_session_are_ignored(self):
        early = b'{"type":"deck_event","id":3,"button":1,"label":"Build"}\n'
        self.assertEqual(panel('COM4', early + info(protocol=2)).info['bootId'], 7)

    def test_another_board_is_rejected_and_its_port_is_closed(self):
        with self.assertRaises(deck.DeviceRejected) as raised:
            panel('COM9', info(boardId='other-esp32'))
        self.assertIn('different device', str(raised.exception))
        self.assertTrue(FakeSerial.opened[0].closed)

    def test_an_unsupported_protocol_asks_for_an_update(self):
        for protocol in (99, 0, '2', None):
            with self.assertRaises(deck.DeviceRejected, msg=repr(protocol)) as raised:
                panel('COM4', info(protocol=protocol))
            self.assertIn('not supported', str(raised.exception))

    def test_silence_and_garbage_are_rejected_not_configured(self):
        for script in (b'', b'not json\n{"type":"info"\n', b'{"type":"wake"}\n'):
            with self.assertRaises(deck.DeviceRejected):
                panel('COM4', script)
        self.assertTrue(all(port.closed for port in FakeSerial.opened))


class RestartTests(unittest.TestCase):
    def test_a_new_boot_id_is_a_restart_and_crashes_get_a_notice(self):
        self.assertIsNone(panel_serial.restart_report(None, {'bootId': 7, 'reset': 'panic'}), 'first connect')
        self.assertIsNone(panel_serial.restart_report(7, {'bootId': 7, 'reset': 'panic'}), 'same boot')
        self.assertEqual(panel_serial.restart_report(7, {'bootId': 8, 'reset': 'sw'}), ('Panel restarted (sw)', None))
        self.assertEqual(panel_serial.restart_report(7, {'bootId': 8})[0], 'Panel restarted (unknown)')
        for reason in ('panic', 'int_wdt', 'task_wdt', 'wdt', 'brownout'):
            line, notice = panel_serial.restart_report(7, {'bootId': 8, 'reset': reason})
            self.assertEqual(line, f'Panel restarted ({reason})')
            self.assertIn('restarted after', notice)

    def test_the_daemon_logs_the_restart_and_adds_a_notice_for_a_crash(self):
        daemon = host_support.test_daemon(port='COM4', no_focus=True)
        daemon.log = Mock()
        daemon.device_info = {'bootId': 8, 'reset': 'task_wdt'}
        daemon.note_panel_restart(7)
        daemon.log.assert_called_once_with('Panel restarted (task_wdt)')
        self.assertEqual(list(daemon.notices)[-1]['title'], 'Tessera panel')
        daemon.device_info = {'bootId': 9, 'reset': 'poweron'}
        daemon.note_panel_restart(8)
        self.assertEqual(len(daemon.notices), 1, 'a normal power-on is only logged')


class OtaPanel(FakeSerial):
    """Acts as the firmware's AD_OTA_* receiver and keeps the image it got."""
    def write(self, raw):
        self.written.extend(raw)
        for line in raw.decode().splitlines():
            if line.startswith('AD_OTA_BEGIN '):
                self.size, self.image = int(line.split()[1]), bytearray()
                self.pending.extend(b'AD_OTA_BEGIN OK\n')
            elif line.startswith('AD_OTA_DATA '):
                _, offset, data = line.split(' ', 2)
                assert int(offset) == len(self.image)
                self.image.extend(bytes.fromhex(data))
                if len(self.image) % panel_serial.OTA_WINDOW == 0 or len(self.image) == self.size:
                    self.pending.extend(f'{{"type":"wake"}}\nAD_OTA_DATA OK {len(self.image)}\n'.encode())
            elif line == 'AD_OTA_END':
                self.pending.extend(self.end_reply)
        return len(raw)


class OtaUploadTests(unittest.TestCase):
    def upload(self, data, end_reply=b'AD_OTA_END OK\n'):
        link = deck.PanelSerial.__new__(deck.PanelSerial)
        link.write_lock, link.rx, link.ser = threading.RLock(), bytearray(), OtaPanel()
        link.ser.end_reply = end_reply
        percents = []
        link.ota_upload(data, percents.append)
        return link.ser, percents

    def test_the_image_arrives_in_order_and_progress_reaches_100(self):
        data = bytes(range(256)) * 21  # not a whole number of chunks
        fake, percents = self.upload(data)
        self.assertEqual(bytes(fake.image), data)
        self.assertEqual(percents[-1], 100)
        self.assertIn(b'AD_OTA_BEGIN 5376 ' + hashlib.sha256(data).hexdigest().encode(), fake.written)

    def test_a_refused_image_raises_with_the_panels_answer(self):
        with self.assertRaises(OSError) as raised:
            self.upload(b'x' * 100, b'AD_OTA_END FAIL checksum\n')
        self.assertIn('FAIL checksum', str(raised.exception))


class PortSelectionTests(unittest.TestCase):
    def daemon(self):
        daemon = host_support.test_daemon(port='COM4', no_focus=True)
        daemon.log = Mock()
        return daemon

    def test_candidate_ports_put_the_remembered_port_first_then_other_espressif_devices(self):
        state = Path(__file__).with_name('no-such-state.json')
        self.assertEqual(candidate_ports('COM4', state, {'COM4': None}, ['COM9', 'COM4', 'COM7']),
                         ['COM4', 'COM7', 'COM9'])

    def test_open_panel_skips_rejected_devices_and_takes_the_first_real_panel(self):
        daemon = self.daemon()
        real = Mock()

        def factory(port, log):
            if port == 'COM7':
                return real
            raise deck.DeviceRejected(f'{port} is a different device')

        daemon.panel_factory = factory
        with patch.object(deck, 'candidate_ports', return_value=['COM4', 'COM7']):
            self.assertEqual(daemon.open_panel(), (real, 'COM7'))

    def test_open_panel_reports_every_failure_when_nothing_matches(self):
        daemon = self.daemon()

        def factory(port, log):
            if port == 'COM4':
                raise deck.DeviceRejected('COM4 is a different device')
            raise OSError('busy')

        daemon.panel_factory = factory
        with patch.object(deck, 'candidate_ports', return_value=['COM4', 'COM7']):
            with self.assertRaises(OSError) as raised:
                daemon.open_panel()
        self.assertIn('COM4 is a different device', str(raised.exception))
        self.assertIn('COM7: busy', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
