"""Device identity and protocol handshake with a scripted serial port; no hardware."""
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck
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
    with patch.object(deck, 'serial', types.SimpleNamespace(Serial=FakeSerial)):
        return deck.PanelSerial(port, Mock())


class HandshakeTests(unittest.TestCase):
    def setUp(self):
        FakeSerial.opened = []
        patcher = patch.object(deck, 'HANDSHAKE_SECONDS', 0.3)
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


class PortSelectionTests(unittest.TestCase):
    def daemon(self):
        daemon = deck.Daemon(types.SimpleNamespace(profiles=str(ROOT / 'host/profiles.default.json'), port='COM4',
                                                   verbose=False, no_focus=True, deck_only=True))
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
