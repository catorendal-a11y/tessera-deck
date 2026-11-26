"""The ESP32-S3 boards on the host side: board ids, screen info, CH340 ports, package names and board checks."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
sys.path.insert(0, str(ROOT / 'tools'))
import firmware_update as fw
import host_runtime
import package_firmware
import panel_serial
import updates
from test_firmware_update import fake_build
from test_handshake import info, panel

S3_BOARDS = ('tessera-s3-ws7', 'tessera-s3-ws7b', 'tessera-s3-8048s070', 'tessera-s3-crowpanel7')


P4_BOARDS = ('tessera-p4', 'tessera-p4-v3', 'tessera-p4-crowpanel7')


class P4BoardTests(unittest.TestCase):
    def test_the_crowpanel_is_a_known_p4_board_with_its_own_package_name(self):
        for board in P4_BOARDS:
            self.assertIn(board, panel_serial.BOARD_IDS)
            self.assertEqual(fw.BOARD_CHIPS[board], 'esp32p4')
        self.assertEqual(fw.package_name('tessera-p4', '1.0.0'), 'tessera-firmware-1.0.0.zip')
        self.assertEqual(fw.package_name('tessera-p4-crowpanel7', '1.0.0'), 'tessera-firmware-tessera-p4-crowpanel7-1.0.0.zip')

    def test_a_v3_chip_gets_its_own_package_and_never_the_v1_one(self):
        assets = [{'name': 'tessera-firmware-1.0.0.zip'}, {'name': 'tessera-firmware-tessera-p4-v3-1.0.0.zip'}]
        self.assertEqual(fw.package_name('tessera-p4-v3', '1.0.0'), 'tessera-firmware-tessera-p4-v3-1.0.0.zip')
        self.assertEqual(updates.firmware_asset(assets, 'tessera-p4-v3')['name'], 'tessera-firmware-tessera-p4-v3-1.0.0.zip')
        self.assertEqual(updates.firmware_asset(assets, 'tessera-p4')['name'], 'tessera-firmware-1.0.0.zip')
        self.assertIsNone(updates.firmware_asset(assets[:1], 'tessera-p4-v3'))
        overlay = (ROOT / 'esp' / 'boards' / 'tessera-p4-v3.defaults').read_text(encoding='utf-8')
        self.assertIn('# CONFIG_ESP32P4_SELECTS_REV_LESS_V3 is not set', overlay)
        self.assertIn('"tessera-p4-v3" if TESSERA_BOARD_P4_GUITION && !ESP32P4_SELECTS_REV_LESS_V3',
                      (ROOT / 'esp' / 'main' / 'Kconfig.projbuild').read_text(encoding='utf-8'))


def table(*entries):
    """A binary partition table: (type, subtype, size) per entry."""
    return b''.join(b'\xaa\x50' + bytes([kind, sub]) + struct.pack('<III', 0x10000, size, 0) + bytes(16)
                    for kind, sub, size in entries)


def fake_ports(*ports):
    tools = types.SimpleNamespace(list_ports=types.SimpleNamespace(comports=lambda: list(ports)))
    return patch.dict(sys.modules, {'serial.tools': tools, 'serial.tools.list_ports': tools.list_ports})


class BoardHandshakeTests(unittest.TestCase):
    def test_every_board_id_is_accepted_and_the_host_and_installer_agree_on_them(self):
        for board in panel_serial.BOARD_IDS:
            self.assertEqual(panel('COM4', info(boardId=board)).info['boardId'], board)
        self.assertEqual(set(panel_serial.BOARD_IDS), set(fw.BOARD_CHIPS))
        with self.assertRaises(panel_serial.DeviceRejected):
            panel('COM4', info(boardId='some-other-board'))

    def test_screen_and_image_cache_come_from_get_info_with_old_firmware_defaults(self):
        new = panel('COM4', info(boardId='tessera-s3-ws7', w=800, h=480, imgCache=2 * 1024 * 1024))
        self.assertEqual((new.screen_size, new.cache_bytes), ((800, 480), 2 * 1024 * 1024))
        old = panel('COM4', info())
        self.assertEqual((old.screen_size, old.cache_bytes), ((1024, 600), 8 * 1024 * 1024))
        junk = panel('COM4', info(w='x', h=0, imgCache=-1))
        self.assertEqual((junk.screen_size, junk.cache_bytes), ((1024, 600), 8 * 1024 * 1024))

    def test_a_protocol_mismatch_keeps_the_panels_info_for_the_installer(self):
        with self.assertRaises(panel_serial.DeviceRejected) as caught:
            panel('COM4', info(boardId='tessera-s3-ws7', protocol=99))
        self.assertEqual(caught.exception.info['boardId'], 'tessera-s3-ws7')

    def test_the_uart_bridge_opens_at_the_uart_speed_with_dtr_and_rts_low(self):
        for vid, expected in ((host_runtime.CH340_VID, host_runtime.UART_BAUD), (host_runtime.ESPRESSIF_VID, 115200)):
            with fake_ports(types.SimpleNamespace(device='COM8', vid=vid)):
                opened = panel('COM8', info(boardId='tessera-s3-8048s070'))
            self.assertEqual((opened.ser.baudrate, opened.ser.dtr, opened.ser.rts), (expected, False, False))


class PortTests(unittest.TestCase):
    def test_ch340_and_espressif_ports_are_both_candidates(self):
        with fake_ports(*[types.SimpleNamespace(device=name, vid=vid) for name, vid in
                          (('COM3', 0x303A), ('COM5', 0x1A86), ('COM6', 0x10C4), ('COM7', None))]):
            self.assertEqual(host_runtime._espressif_ports(), ['COM3', 'COM5'])

    def test_a_bridge_without_a_serial_number_is_followed_by_its_port_name(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'device.json'
            host_runtime.remember_port('COM8', state, {'COM8': None, 'COM4': 'X'})
            self.assertEqual(json.loads(state.read_text()), {'port': 'COM8'})
            self.assertEqual(host_runtime.resolve_port('COM4', state, {'COM8': '', 'COM4': 'X'}), 'COM8')
            self.assertEqual(host_runtime.resolve_port('COM4', state, {'COM4': 'X'}), 'COM4')  # unplugged: default
            host_runtime.remember_port('COM9', state, {'COM9': 'ABC'})  # a serial number wins from then on
            self.assertEqual(json.loads(state.read_text()), {'serial': 'ABC'})


class PackageBoardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def build(self, board, chip, bootloader='0x2000'):
        build = fake_build(self.folder / board)
        args = json.loads((build / 'flasher_args.json').read_text())
        args['flash_files'] = {(bootloader if key == '0x2000' else key): value for key, value in args['flash_files'].items()}
        (build / 'flasher_args.json').write_text(json.dumps(args))
        return fw.build_package(build, self.folder / 'dist', '1.0.0', 4, board, chip)

    def test_package_names_keep_the_p4_name_and_add_the_board_for_the_others(self):
        self.assertEqual(self.build('tessera-p4', 'esp32p4').name, 'tessera-firmware-1.0.0.zip')
        for board in S3_BOARDS:
            self.assertEqual(self.build(board, 'esp32s3', '0x0').name, f'tessera-firmware-{board}-1.0.0.zip')
        with self.assertRaises(fw.PackageError):
            fw.build_package(fake_build(self.folder / 'wrong'), self.folder / 'dist', '1.0.0', 4, 'tessera-s3-ws7', 'esp32p4')

    def test_an_s3_package_loads_flashes_with_the_s3_chip_and_keeps_the_bootloader_at_zero(self):
        package = fw.load_package(self.build('tessera-s3-ws7', 'esp32s3', '0x0'), (4,))
        self.assertEqual((package.board, package.chip), ('tessera-s3-ws7', 'esp32s3'))
        command = fw.command_line(package, 'COM4', Path('x'), 'full')
        self.assertEqual(command[command.index('--chip') + 1], 'esp32s3')
        self.assertEqual([part for part in command if part.startswith('0x')], ['0x0', '0x8000', '0x10000'])

    def test_a_manifest_with_a_wrong_chip_or_unknown_board_is_refused(self):
        path = self.build('tessera-s3-ws7', 'esp32s3', '0x0')
        for change in ({'chip': 'esp32p4'}, {'board': 'nope'}, {'board': None}):
            with zipfile.ZipFile(path) as source:
                members = {name: source.read(name) for name in source.namelist()}
            members['manifest.json'] = json.dumps(dict(json.loads(members['manifest.json']), **change)).encode()
            bad = self.folder / 'bad.zip'
            with zipfile.ZipFile(bad, 'w') as target:
                for name, data in members.items():
                    target.writestr(name, data)
            with self.assertRaises(fw.PackageError):
                fw.load_package(bad, (4,))

    def test_install_refuses_a_package_for_another_board_in_both_modes(self):
        package = fw.load_package(self.build('tessera-s3-ws7', 'esp32s3', '0x0'), (4,))
        runner, ota = Mock(return_value=(0, '')), Mock()
        for mode in ('app', 'full'):
            for board in ('tessera-p4', 'tessera-s3-8048s070'):
                with self.assertRaisesRegex(fw.InstallError, 'is for tessera-s3-ws7'):
                    fw.install(package, 'COM4', lambda port, board=board: {'boardId': board, 'ota': 1},
                               mode=mode, runner=runner, ota=ota)
        runner.assert_not_called()
        ota.assert_not_called()
        fw.install(package, 'COM4', lambda port: {'boardId': 'tessera-s3-ws7'}, mode='full', runner=runner)
        runner.assert_called_once()

    def test_the_application_must_fit_its_slot(self):
        build = fake_build(self.folder / 'slot')
        (build / 'partition_table/partition-table.bin').write_bytes(table((1, 2, 0x6000), (0, 0x10, 0x800)))
        path = fw.build_package(build, self.folder / 'dist', '1.0.0', 4)
        with self.assertRaisesRegex(fw.PackageError, 'does not fit'):
            fw.load_package(path, (4,))
        (build / 'partition_table/partition-table.bin').write_bytes(table((0, 0x10, 0x100000)))
        self.assertEqual(fw.load_package(fw.build_package(build, self.folder / 'dist2', '1.0.0', 4), (4,)).version, '1.0.0')

    def test_package_firmware_detects_ota_slots_in_the_partition_table(self):
        self.assertTrue(package_firmware.has_ota_slots(table((1, 2, 0x6000), (1, 0, 0x2000))))
        self.assertFalse(package_firmware.has_ota_slots(table((1, 2, 0x6000), (0, 0x10, 0x1000))))

    def test_package_firmware_refuses_a_board_that_does_not_match_the_build(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            (build / 'config').mkdir()
            (build / 'config/sdkconfig.json').write_text(json.dumps({'TESSERA_BOARD_ID': 'tessera-p4-crowpanel7'}))
            with patch.object(sys, 'argv', ['package_firmware.py', str(build), str(build / 'dist')]),                     self.assertRaisesRegex(SystemExit, 'pass --board tessera-p4-crowpanel7'):
                package_firmware.main()


class ReleaseAssetTests(unittest.TestCase):
    ASSETS = [{'name': name, 'size': 1, 'url': 'https://github.com/r/' + name} for name in (
        'tessera-firmware-1.0.0.zip', 'tessera-firmware-tessera-s3-ws7-1.0.0.zip',
        'tessera-firmware-tessera-s3-8048s070-1.0.0.zip', 'SHA256SUMS')]

    def test_each_board_gets_its_own_package_and_the_p4_keeps_the_old_name(self):
        def pick(board):
            return updates.firmware_asset(self.ASSETS, board)['name']
        self.assertEqual(pick('tessera-p4'), 'tessera-firmware-1.0.0.zip')
        self.assertEqual(pick(None), 'tessera-firmware-1.0.0.zip')
        self.assertEqual(pick('tessera-s3-ws7'), 'tessera-firmware-tessera-s3-ws7-1.0.0.zip')
        self.assertEqual(pick('tessera-s3-8048s070'), 'tessera-firmware-tessera-s3-8048s070-1.0.0.zip')
        self.assertIsNone(updates.firmware_asset(self.ASSETS[:1], 'tessera-s3-ws7'))


if __name__ == '__main__':
    unittest.main()
