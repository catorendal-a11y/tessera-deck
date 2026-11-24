"""Device identity and protocol handshake with a scripted serial port; no hardware."""
import errno
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

    def test_the_port_is_locked_for_this_host_while_it_is_open(self):
        # pyserial takes flock on POSIX only when `exclusive` is set before open(); esptool and idf.py take the same
        # lock, so with it they report a busy port instead of flashing through the host's pings.
        class Locking(FakeSerial):
            exclusive = None

            def open(self):
                self.locked = self.exclusive

        FakeSerial.script = info(protocol=2)
        with patch.object(panel_serial, 'serial', types.SimpleNamespace(Serial=Locking)):
            deck.PanelSerial('COM4', Mock())
        self.assertIs(FakeSerial.opened[0].locked, True)
        refused = OSError(errno.EAGAIN, 'Could not exclusively lock port /dev/ttyUSB0: [Errno 11] Resource temporarily unavailable')
        self.assertIn('in use by another program', deck.port_trouble('/dev/ttyUSB0', refused))

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


class RestartOnTheSameLinkTests(unittest.TestCase):
    """A board with a USB-UART bridge that restarts (RST, a crash, a power dip) stays on USB, so the port never fails:
    the host must notice the new boot from what the panel says, or the panel keeps an old page with no rail or lock."""

    def connected(self, boot_after):
        FakeSerial.opened = []
        link = panel('COM9', info(bootId=7, protocol=4))
        daemon = host_support.test_daemon(port='COM9', no_focus=True)
        daemon.log, daemon.publish_runtime = Mock(), Mock()
        daemon.panel, daemon.device_info = link, link.info
        FakeSerial.script = info(bootId=boot_after, protocol=4)  # what the panel answers from now on
        reader = threading.Thread(target=daemon.reader_loop, args=(link,), daemon=True)
        reader.start()
        self.addCleanup(reader.join, 2)
        self.addCleanup(daemon.stop.set)
        import time
        for second in range(1, 31):  # half a minute of heartbeats
            daemon.heartbeat(link, time.monotonic() + second)
        return daemon

    def test_a_panel_that_restarted_without_leaving_usb_is_connected_again(self):
        self.assertTrue(self.connected(boot_after=8).connection_failed.wait(2))

    def test_the_same_boot_keeps_the_connection(self):
        self.assertFalse(self.connected(boot_after=7).connection_failed.wait(0.5))


class OtaPanel(FakeSerial):
    """Acts as the firmware's AD_OTA_* receiver and keeps the image it got. `lost` names the windows (1 is the first)
    whose answer never leaves the panel, `late` those whose answer only comes with the next one, and `dropped` the
    data lines the panel never gets."""
    lost, late, dropped = (), (), ()

    def write(self, raw):
        self.written.extend(raw)
        for line in raw.decode().splitlines():
            if line.startswith('AD_OTA_BEGIN '):
                self.size, self.image, self.lines, self.held = int(line.split()[1]), bytearray(), 0, b''
                self.pending.extend(b'AD_OTA_BEGIN OK\n')
            elif line.startswith('AD_OTA_DATA '):
                self.lines += 1
                if self.lines in self.dropped:
                    continue
                _, offset, data = line.split(' ', 2)
                if int(offset) != len(self.image):  # as the firmware does: refuse and forget the upload
                    self.pending.extend(b'AD_OTA_DATA FAIL offset\n')
                    continue
                self.image.extend(bytes.fromhex(data))
                if len(self.image) % panel_serial.OTA_WINDOW == 0 or len(self.image) == self.size:
                    window = -(-len(self.image) // panel_serial.OTA_WINDOW)
                    answer = f'{{"type":"wake"}}\nAD_OTA_DATA OK {len(self.image)}\n'.encode()
                    if window in self.late:
                        self.held = answer
                    elif window not in self.lost:
                        self.pending.extend(self.held + answer)
                        self.held = b''
            elif line == 'AD_OTA_END':
                self.pending.extend(self.end_reply)
        return len(raw)


class OtaUploadTests(unittest.TestCase):
    def upload(self, data, end_reply=b'AD_OTA_END OK\n', **faults):
        link = deck.PanelSerial.__new__(deck.PanelSerial)
        link.write_lock, link.rx, link.ser = threading.RLock(), bytearray(), OtaPanel()
        link.ser.end_reply = end_reply
        vars(link.ser).update(faults)
        percents = []
        with patch.object(panel_serial, 'OTA_ANSWER_SECONDS', .05):
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

    def test_an_answer_the_panel_lost_does_not_stop_the_upload(self):
        # measured on a GUITION panel with firmware 1.2.9: 1 answer in 12216 never left it, and it had all the data
        data = bytes(range(256)) * 40  # five windows
        for lost in ((2,), (2, 3), (5,)):  # one, two in a row, and the last one before AD_OTA_END
            with self.subTest(lost=lost):
                fake, percents = self.upload(data, lost=lost)
                self.assertEqual(bytes(fake.image), data)
                self.assertIn(b'AD_OTA_END\n', fake.written)
                self.assertEqual(percents, sorted(percents))

    def test_an_answer_that_comes_late_is_passed_over(self):
        data = bytes(range(256)) * 40
        fake, percents = self.upload(data, late=(2,))
        self.assertEqual(bytes(fake.image), data)
        self.assertEqual(percents[-1], 100)

    def test_a_panel_that_stays_silent_window_after_window_is_a_timeout(self):
        with self.assertRaisesRegex(TimeoutError, 'AD_OTA_DATA'):
            self.upload(bytes(range(256)) * 40, lost=(2, 3, 4))

    def test_data_the_panel_never_got_is_refused_by_the_panel_and_reported(self):
        with self.assertRaises(OSError) as raised:
            self.upload(bytes(range(256)) * 40, dropped=(6,))  # a line of the second window
        self.assertIn('FAIL offset', str(raised.exception))
        self.assertNotIsInstance(raised.exception, TimeoutError)


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

    def test_open_panel_says_in_plain_words_why_a_port_does_not_open(self):
        daemon = self.daemon()
        errors = {'COM4': OSError("could not open port 'COM4': PermissionError(13, 'Access is denied.', None, 5)"),
                  'COM7': OSError("could not open port 'COM7': FileNotFoundError(2, 'The system cannot find the file specified.', None, 2)"),
                  '/dev/ttyACM0': OSError(errno.EACCES, 'could not open port /dev/ttyACM0: Permission denied'),
                  '/dev/ttyACM1': OSError(errno.EBUSY, 'could not open port /dev/ttyACM1: Device or resource busy')}

        def factory(port, log):
            raise errors[port]

        daemon.panel_factory = factory
        with patch.object(deck, 'candidate_ports', return_value=list(errors)):
            with self.assertRaises(OSError) as raised:
                daemon.open_panel()
        text = str(raised.exception)
        self.assertIn('COM4 is in use by another program', text)
        self.assertIn('COM7 is not there', text)
        self.assertIn('/dev/ttyACM0 may not be opened by your user', text)
        self.assertIn('/dev/ttyACM1 is in use by another program', text)
        self.assertNotIn('PermissionError', text)

    def test_windows_errors_that_need_a_replug_say_so(self):
        import serial

        def refused(error):  # as serialwin32 raises it, with repr(ctypes.WinError(code)) as printed by Python 3.11
            return serial.SerialException(f"could not open port 'COM4': {error}")
        replug = ("PermissionError(13, 'A device attached to the system is not functioning.', None, 31)",  # after sleep
                  "PermissionError(13, 'The device does not recognize the command.', None, 22)",
                  "OSError(22, 'The semaphore timeout period has expired.', None, 121)",  # an absent Bluetooth COM port
                  "OSError(22, 'A device which does not exist was specified.', None, 433)")
        for error in replug:
            with self.subTest(error=error):
                said = deck.port_trouble('COM4', refused(error))
                self.assertIn('Unplug', said)
                self.assertNotIn('in use', said)
                self.assertNotIn('firmware', said)
        for error in ("PermissionError(13, 'Access is denied.', None, 5)",
                      "PermissionError(13, 'The process cannot access the file because it is being used by another process.', None, 32)"):
            self.assertIn('in use', deck.port_trouble('COM4', refused(error)))
        self.assertIn('no firmware yet', deck.port_trouble('COM4', serial.SerialTimeoutException('Write timeout')))

    def test_a_device_that_goes_away_during_the_handshake_says_to_replug_it(self):
        import serial
        # pyserial 3.5 serialwin32 wraps repr(ctypes.WinError()) in brackets once the port is open, so the code is not last
        errors = ("WriteFile failed (OSError(22, 'The device is not connected.', None, 1167))",
                  "ReadFile failed (PermissionError(13, 'A device attached to the system is not functioning.', None, 31))",
                  "ClearCommError failed (PermissionError(13, 'The device does not recognize the command.', None, 22))",
                  "GetOverlappedResult failed (OSError(22, 'The semaphore timeout period has expired.', None, 121))",
                  "Cannot configure port, something went wrong. Original message: "
                  "OSError(22, 'A device which does not exist was specified.', None, 433)",
                  # The port is already ours, and Windows opens COM ports exclusively, so access denied here is not another
                  # program: usbser.sys, the driver of the P4's USB Serial/JTAG, answers 5 once the device is pulled.
                  "WriteFile failed (PermissionError(13, 'Access is denied.', None, 5))",
                  "ClearCommError failed (PermissionError(13, 'Access is denied.', None, 5))")
        for error in errors:
            with self.subTest(error=error):
                self.assertEqual(deck.port_trouble('COM4', serial.SerialException(error)),
                                 'The USB device on COM4 stopped responding. Unplug it and plug it in again.')


class ReconnectProbeTests(unittest.TestCase):
    """What the reconnect loop opens while no panel answers. Every open of a UART board restarts it on Linux, and on
    Windows it holds the port for the handshake, so another program's upload or monitor gets "Access is denied"."""
    DEVKIT = types.SimpleNamespace(device='COM8', vid=0x303A, serial_number='DEVKIT1')  # someone's ESP32-S3 devkit
    CLONE = types.SimpleNamespace(device='COM9', vid=0x1A86, serial_number=None)  # an Arduino clone with a CH340

    def setUp(self):
        import os
        import tempfile
        FakeSerial.opened, FakeSerial.script = [], b''  # nothing on any port answers get_info
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.state = Path(folder.name) / 'deck-device.local.json'
        self.state.write_text(json.dumps({'serial': 'PANEL123'}), encoding='utf-8')  # a panel was used before
        self.listed = [self.DEVKIT, self.CLONE]
        for patcher in (patch.object(panel_serial, 'HANDSHAKE_SECONDS', 0.05),
                        patch.object(panel_serial, 'serial', types.SimpleNamespace(Serial=FakeSerial)),
                        patch('serial.tools.list_ports.comports', lambda: list(self.listed)),
                        patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop('TESSERA_PORT', None)

    def daemon(self, port='COM4'):
        daemon = host_support.test_daemon(port=port, no_focus=True)
        daemon.log, daemon.device_state_path = Mock(), self.state
        return daemon

    def attempts(self, daemon, count):
        for _ in range(count):
            with self.assertRaises(OSError):
                daemon.open_panel()
        return [fake.port for fake in FakeSerial.opened]

    def test_other_devices_are_left_alone_after_a_few_silent_answers(self):
        opened = self.attempts(self.daemon(), 8)  # the panel is unplugged: about a minute of retries
        self.assertLessEqual(opened.count('COM8'), 3)
        self.assertLessEqual(opened.count('COM9'), 3)

    def test_a_device_that_was_unplugged_and_plugged_in_again_is_asked_again(self):
        daemon = self.daemon()
        self.attempts(daemon, 4)
        self.listed = [self.CLONE]
        self.attempts(daemon, 1)
        self.listed = [self.DEVKIT, self.CLONE]
        FakeSerial.opened = []
        self.assertIn('COM8', self.attempts(daemon, 1))

    def test_the_remembered_panel_is_asked_on_every_attempt_even_when_it_stays_silent(self):
        self.listed = [types.SimpleNamespace(device='COM5', vid=0x1A86, serial_number='PANEL123')]  # hung, still on USB
        self.assertEqual(self.attempts(self.daemon(), 6).count('COM5'), 6)

    def test_a_panel_with_firmware_this_host_does_not_speak_is_opened_once_and_the_reason_stays(self):
        self.state.write_text(json.dumps({'port': 'COM6'}), encoding='utf-8')  # the CH340 panel, used before
        self.listed = [types.SimpleNamespace(device='COM6', vid=0x1A86, serial_number=None)]
        FakeSerial.script = info(boardId='tessera-s3-crowpanel7', protocol=99)  # a newer firmware zip, an older host
        daemon = self.daemon(port='')
        for _ in range(4):
            with self.assertRaises(OSError) as raised:
                daemon.open_panel()
            self.assertIn('update the firmware or the host', str(raised.exception))
        self.assertEqual([fake.port for fake in FakeSerial.opened], ['COM6'])

    def test_a_new_user_hears_about_the_blank_panel_not_about_a_busy_com4(self):
        import serial

        class Ports(FakeSerial):
            def open(self):
                if self.port == 'COM4':  # a modem or Bluetooth port another program holds
                    raise serial.SerialException("could not open port 'COM4': PermissionError(13, 'Access is denied.', None, 5)")

            def write(self, raw):  # nothing reads on a panel without firmware
                raise serial.SerialTimeoutException('Write timeout')

        self.state.unlink()  # no panel was connected before
        self.listed = [types.SimpleNamespace(device='COM4', vid=None, serial_number=None),
                       types.SimpleNamespace(device='COM7', vid=0x303A, serial_number='P4BLANK')]
        with patch.object(panel_serial, 'serial', types.SimpleNamespace(Serial=Ports)), \
                self.assertRaises(OSError) as raised:
            self.daemon(port='COM4').open_panel()  # COM4 is the Windows default the host is started with
        self.assertIn('COM7 does not take data', str(raised.exception))
        self.assertNotIn('in use', str(raised.exception))

    def test_an_arduino_held_by_another_program_does_not_hide_the_blank_panel_in_the_editor(self):
        import serial
        from test_editor import run_editor

        class Ports(FakeSerial):
            def open(self):
                if self.port == 'COM4':  # an Arduino clone with a CH340, its serial monitor open in Arduino IDE
                    raise serial.SerialException("could not open port 'COM4': PermissionError(13, 'Access is denied.', None, 5)")

            def write(self, raw):
                if self.port == 'COM7' and usb_jtag:  # nothing reads the USB Serial/JTAG port of a P4 without firmware
                    raise serial.SerialTimeoutException('Write timeout')
                return super().write(raw)

        self.state.unlink()  # a new user: no panel was connected before
        FakeSerial.script = b'ESP-ROM:esp32s3-20210327\r\nwaiting for download\r\n'  # the ROM of a blank UART board
        for usb_jtag in (True, False):
            with self.subTest(usb_jtag=usb_jtag):
                self.listed = [types.SimpleNamespace(device='COM4', vid=0x1A86, serial_number=None),
                               types.SimpleNamespace(device='COM7', vid=0x303A if usb_jtag else 0x1A86, serial_number=None)]
                with patch.object(panel_serial, 'serial', types.SimpleNamespace(Serial=Ports)), \
                        self.assertRaises(OSError) as raised:
                    self.daemon(port='COM4').open_panel()
                error = str(raised.exception)
                self.assertIn('COM4 is in use', error)  # a CH340 can be a panel, so the host still asks it
                said = run_editor(self, f'return panelProblem({json.dumps(error)});')
                self.assertTrue(said[0].startswith('No panel found'), said[0])
                self.assertEqual(said[1][0], 'Panel firmware …')
                self.assertEqual(said[2], error)  # the second line still names the busy COM4

    def test_with_tessera_port_set_only_that_port_is_opened(self):
        import os
        os.environ['TESSERA_PORT'] = 'COM8'
        self.assertEqual(set(self.attempts(self.daemon(port='COM8'), 3)), {'COM8'})


if __name__ == '__main__':
    unittest.main()
