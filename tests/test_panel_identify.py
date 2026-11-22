"""A port that does not answer as a Tessera panel: what it printed goes into the error, so a report shows why."""
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
sys.path.insert(0, str(ROOT / 'tools'))
import panel_serial
from v3_sdkconfig import v3_sdkconfig


class Printing:
    """A pyserial port whose firmware prints but never answers get_info."""

    def __init__(self, output):
        self.port, self.queue = 'COM7', [output]

    def reset_input_buffer(self):
        pass

    def write(self, raw):
        return len(raw)

    in_waiting = property(lambda self: len(self.queue[0]) if self.queue else 0)

    def read(self, size):
        return self.queue.pop(0) if self.queue else b''


def silent_panel(output):
    panel = panel_serial.PanelSerial.__new__(panel_serial.PanelSerial)
    panel.ser, panel.rx, panel.write_lock, panel.log = Printing(output), bytearray(), threading.RLock(), lambda *a: None
    return panel


class SilentPortTests(unittest.TestCase):
    def rejected(self, output):
        with patch.object(panel_serial, 'HANDSHAKE_SECONDS', 0.05), self.assertRaises(panel_serial.DeviceRejected) as raised:
            silent_panel(output).verify()
        self.assertEqual(raised.exception.kind, 'silent')
        return str(raised.exception)

    def test_the_last_lines_it_printed_are_in_the_error(self):
        log = b'ESP-ROM:esp32p4-eco2\nbuild:Mar 2025\nI (25) boot: chip revision: v3.2\n{"type":"key"}\n\n' \
              b"Guru Meditation Error: Core  0 panic'ed (Load access fault)\nRebooting...\n"
        message = self.rejected(log)
        self.assertIn('did not identify itself', message)
        self.assertIn("Guru Meditation Error: Core  0 panic'ed (Load access fault) | Rebooting...", message)
        self.assertNotIn('ESP-ROM', message)  # only the last four lines
        self.assertNotIn('"type"', message)

    def test_a_port_that_prints_nothing_says_only_that(self):
        self.assertEqual(self.rejected(b''), 'COM7 did not identify itself as a Tessera panel')


class V3ConfigTests(unittest.TestCase):
    def test_the_v3_start_is_the_tested_v1_config_without_the_revision_options(self):
        tested = (ROOT / 'sdkconfig').read_text(encoding='utf-8')
        v3 = v3_sdkconfig(tested)
        for gone in ('CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y', 'CONFIG_ESP32P4_REV_MIN_100=y', 'CONFIG_ESP32P4_REV_MAX_FULL=',
                     'CONFIG_ESP_REV_MIN_FULL=', 'CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_360=y', 'CONFIG_TESSERA_BOARD_ID=',
                     'CONFIG_BOOTLOADER_LOG_LEVEL_INFO=y'):
            self.assertIn(gone, tested)
            self.assertNotIn(gone, v3)
        for kept in ('CONFIG_LV_DRAW_THREAD_STACK_SIZE=16384', 'CONFIG_ESP_INT_WDT_TIMEOUT_MS=2000',
                     'CONFIG_SPIRAM_XIP_FROM_PSRAM=y', 'CONFIG_TESSERA_BOARD_P4_GUITION=y'):
            self.assertIn(kept, v3)


if __name__ == '__main__':
    unittest.main()
