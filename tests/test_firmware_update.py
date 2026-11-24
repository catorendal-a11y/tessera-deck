"""Firmware packages and installation, with a fake esptool; nothing is flashed."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import firmware_update as fw
from tessera_app import Editor
from panel_serial import DeviceRejected

SUPPORTED = (1, 2)


def fake_build(folder: Path, slots: bool = False) -> Path:
    """An ESP-IDF build folder; slots=True is the A/B partition table with its OTA data image."""
    build = folder / 'build'
    (build / 'bootloader').mkdir(parents=True)
    (build / 'partition_table').mkdir()
    (build / 'bootloader/bootloader.bin').write_bytes(b'boot' * 100)
    (build / 'partition_table/partition-table.bin').write_bytes(b'part' * 50)
    (build / 'tessera.bin').write_bytes(b'app!' * 1000)
    files = {'0x2000': 'bootloader/bootloader.bin', '0x8000': 'partition_table/partition-table.bin',
             '0x10000': 'tessera.bin'}
    if slots:
        (build / 'ota_data_initial.bin').write_bytes(bytes([255]) * 8192)
        files['0xd000'] = 'ota_data_initial.bin'
    (build / 'flasher_args.json').write_text(json.dumps({
        'flash_settings': {'flash_mode': 'dio', 'flash_size': '16MB', 'flash_freq': '80m'}, 'flash_files': files}))
    return build


def rewrite(path: Path, files_data=None, **changes):
    """Rewrite the manifest of a package (and optionally replace files in it)."""
    with zipfile.ZipFile(path) as source:
        members = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(members['manifest.json'])
    manifest.update(changes)
    members['manifest.json'] = json.dumps(manifest).encode()
    members.update(files_data or {})
    with zipfile.ZipFile(path, 'w') as target:
        for name, data in members.items():
            target.writestr(name, data)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.package_path = fw.build_package(fake_build(self.folder), self.folder / 'dist', '1.2.3', 2)

    def test_a_built_package_loads_with_every_image_verified(self):
        package = fw.load_package(self.package_path, SUPPORTED)
        self.assertEqual((package.version, package.protocol), ('1.2.3', 2))
        self.assertEqual([hex(image.offset) for image in package.images], ['0x2000', '0x8000', '0x10000'])
        self.assertEqual(package.app.data, b'app!' * 1000)
        checksum = (self.package_path.parent / (self.package_path.name + '.sha256')).read_text().split()[0]
        self.assertEqual(checksum, fw.sha256(self.package_path.read_bytes()))

    def test_a_damaged_image_is_refused(self):
        rewrite(self.package_path, files_data={'tessera.bin': b'tampered'})
        with self.assertRaises(fw.PackageError) as raised:
            fw.load_package(self.package_path, SUPPORTED)
        self.assertIn('checksum', str(raised.exception))

    def test_other_boards_chips_formats_and_protocols_are_refused(self):
        for change, text in ((dict(board='other'), 'not for a Tessera'), (dict(chip='esp32s3'), 'not for a Tessera'),
                             (dict(format=9), 'format'), (dict(protocol=99), 'protocol'),
                             (dict(protocol='2'), 'protocol'), (dict(version=''), 'incomplete')):
            path = self.folder / 'copy.zip'
            path.write_bytes(self.package_path.read_bytes())
            rewrite(path, **change)
            with self.assertRaises(fw.PackageError, msg=repr(change)) as raised:
                fw.load_package(path, SUPPORTED)
            self.assertIn(text, str(raised.exception), msg=repr(change))

    def test_path_traversal_and_missing_files_are_refused(self):
        for files, text in (([{'offset': '0x10000', 'file': '../evil.bin', 'sha256': 'x'}], 'Unsafe'),
                            ([{'offset': '0x10000', 'file': 'gone.bin', 'sha256': 'x'}], 'missing'),
                            ([{'offset': 'zz', 'file': 'tessera.bin', 'sha256': 'x'}], 'unreadable'),
                            ([], 'no application image')):
            path = self.folder / 'copy.zip'
            path.write_bytes(self.package_path.read_bytes())
            rewrite(path, files=files)
            with self.assertRaises(fw.PackageError, msg=text) as raised:
                fw.load_package(path, SUPPORTED)
            self.assertIn(text, str(raised.exception))

    def test_garbage_files_are_not_packages(self):
        path = self.folder / 'junk.zip'
        path.write_bytes(b'not a zip at all')
        with self.assertRaises(fw.PackageError):
            fw.load_package(path, SUPPORTED)
        with self.assertRaises(fw.PackageError):
            fw.load_package(self.folder / 'missing.zip', SUPPORTED)

    def test_app_mode_writes_only_the_application_and_full_mode_everything(self):
        package = fw.load_package(self.package_path, SUPPORTED)
        app = fw.command_line(package, 'COM4', Path('x'), 'app')
        self.assertEqual(app[app.index('write-flash') + 7:], ['0x10000', str(Path('x') / 'tessera.bin')])
        full = fw.command_line(package, 'COM4', Path('x'), 'full')
        self.assertEqual([part for part in full if part.startswith('0x')], ['0x2000', '0x8000', '0x10000'])
        self.assertIn('esp32p4', full)
        with self.assertRaises(ValueError):
            fw.command_line(package, 'COM4', Path('x'), 'erase')

    def test_an_ab_package_carries_the_ota_data_and_app_mode_resets_it(self):
        path = fw.build_package(fake_build(self.folder / 'ab', slots=True), self.folder / 'ab-dist', '2.0.0', 4)
        package = fw.load_package(path, (4,))
        self.assertTrue(package.needs_full)
        self.assertEqual(package.otadata.offset, 0xd000)
        app = fw.command_line(package, 'COM4', Path('x'), 'app')
        self.assertEqual([part for part in app if part.startswith('0x')], ['0xd000', '0x10000'])
        self.assertFalse(fw.load_package(self.package_path, SUPPORTED).needs_full)
        self.assertTrue(fw.find_packages([path.parent], (4,))[0]['needs_full'])

    def test_find_packages_lists_valid_and_damaged_ones(self):
        (self.package_path.parent / 'tessera-firmware-9.9.9.zip').write_bytes(b'broken')
        found = fw.find_packages([self.package_path.parent, self.folder / 'nowhere'], SUPPORTED)
        self.assertEqual({item['version'] for item in found}, {'1.2.3', None})
        self.assertEqual(sum(1 for item in found if item['error']), 1)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.package = fw.load_package(fw.build_package(fake_build(folder), folder / 'dist', '1.2.3', 2), SUPPORTED)

    def test_a_verified_panel_is_flashed_with_progress_and_the_previous_version_is_reported(self):
        stages, seen = [], []

        def runner(arguments, progress):
            seen.append(arguments)
            progress(10.0)
            progress(100.0)
            return 0, ''

        result = fw.install(self.package, 'COM4', lambda port: {'boardId': 'tessera-p4', 'firmwareVersion': '1.0.0'},
                            progress=lambda stage, percent: stages.append((stage, percent)), runner=runner)
        self.assertEqual(result, {'previous': '1.0.0', 'installed': '1.2.3', 'mode': 'app'})
        self.assertIn('0x10000', seen[0])
        self.assertEqual(stages[0], ('checking', 0))
        self.assertIn(('writing', 100.0), stages)
        self.assertEqual(stages[-1], ('done', 100))

    def test_a_chip_revision_refusal_names_the_package_for_the_other_revision(self):
        refusal = 'A fatal error occurred: bootloader.bin requires chip revision in range [v1.0 - v1.99] (this chip is revision v3.2)'
        with self.assertRaisesRegex(fw.InstallError, 'tessera-p4-v3 package'):
            fw.install(self.package, 'COM4', lambda port: None, force=True, runner=Mock(return_value=(2, refusal)))

    def test_a_silent_panel_needs_an_explicit_force_and_another_board_is_never_touched(self):
        runner = Mock(return_value=(0, ''))
        with self.assertRaises(fw.InstallError):
            fw.install(self.package, 'COM4', lambda port: None, runner=runner)
        runner.assert_not_called()
        fw.install(self.package, 'COM4', lambda port: None, force=True, runner=runner)
        runner.assert_called_once()

        def other(port):
            raise fw.PackageError('COM4 is a different device')

        runner.reset_mock()
        with self.assertRaises(fw.PackageError):
            fw.install(self.package, 'COM4', other, force=True, runner=runner)
        runner.assert_not_called()

    def test_a_failed_flash_explains_how_to_recover(self):
        with self.assertRaises(fw.InstallError) as raised:
            fw.install(self.package, 'COM4', lambda port: {'firmwareVersion': '1'},
                       runner=lambda arguments, progress: (2, 'A fatal error occurred: timed out'))
        self.assertIn('retry', str(raised.exception))
        self.assertIn('timed out', str(raised.exception))

    def ab_package(self):
        folder = Path(tempfile.mkdtemp(dir=self.temp.name))
        return fw.load_package(fw.build_package(fake_build(folder, slots=True), folder / 'dist', '2.0.0', 2), SUPPORTED)

    def test_the_first_ab_install_needs_everything(self):
        runner, ota = Mock(return_value=(0, '')), Mock()
        for answer in ({'firmwareVersion': '1.0.0'}, None):
            with self.assertRaises(fw.InstallError) as raised:
                fw.install(self.ab_package(), 'COM4', lambda port, answer=answer: answer, force=True, runner=runner, ota=ota)
            self.assertIn('Full install', str(raised.exception))
        runner.assert_not_called()
        ota.assert_not_called()
        fw.install(self.ab_package(), 'COM4', lambda port: {'firmwareVersion': '1.0.0'}, mode='full', runner=runner)
        runner.assert_called_once()

    def test_a_panel_with_slots_is_updated_over_usb_not_with_esptool(self):
        runner, sent, stages = Mock(return_value=(0, '')), [], []

        def ota(port, data, progress):
            sent.append((port, data))
            progress(50.0)

        package = self.ab_package()
        result = fw.install(package, 'COM4', lambda port: {'firmwareVersion': '1.9.0', 'ota': 1}, runner=runner,
                            ota=ota, progress=lambda stage, percent: stages.append((stage, percent)))
        self.assertEqual(sent, [('COM4', package.app.data)])
        runner.assert_not_called()
        self.assertEqual(result, {'previous': '1.9.0', 'installed': '2.0.0', 'mode': 'app'})
        self.assertIn(('writing', 50.0), stages)
        self.assertEqual(stages[-1], ('done', 100))

    def test_a_failed_usb_update_keeps_the_old_firmware_and_says_so(self):
        def ota(port, data, progress):
            raise OSError('AD_OTA_END FAIL checksum')

        with self.assertRaises(fw.InstallError) as raised:
            fw.install(self.ab_package(), 'COM4', lambda port: {'ota': 1}, ota=ota)
        self.assertIn('FAIL checksum', str(raised.exception))
        self.assertIn('current firmware', str(raised.exception))

    def test_an_older_single_slot_firmware_goes_back_only_with_everything(self):
        runner, ota = Mock(return_value=(0, '')), Mock()
        with self.assertRaises(fw.InstallError):
            fw.install(self.package, 'COM4', lambda port: {'ota': 1}, runner=runner, ota=ota)
        ota.assert_not_called()
        fw.install(self.package, 'COM4', lambda port: {'ota': 1}, mode='full', runner=runner, ota=ota)
        runner.assert_called_once()
        ota.assert_not_called()

    def test_a_panel_with_a_protocol_this_host_does_not_speak_gets_only_the_full_install(self):
        runner, ota = Mock(return_value=(0, '')), Mock()
        unknown = lambda port: {'boardId': fw.BOARD_ID, 'firmwareVersion': None, 'protocolUnknown': True}  # noqa: E731
        with self.assertRaises(fw.InstallError) as raised:
            fw.install(self.ab_package(), 'COM4', unknown, runner=runner, ota=ota)
        self.assertIn('Wi-Fi beta', str(raised.exception))
        self.assertNotIn('A/B', str(raised.exception))
        runner.assert_not_called()
        fw.install(self.ab_package(), 'COM4', unknown, mode='full', runner=runner, ota=ota)
        runner.assert_called_once()
        ota.assert_not_called()

    def test_esptool_progress_lines_are_parsed(self):
        self.assertEqual(fw.PROGRESS.findall('Writing at 0x0002bf4c [=====>   ]  42.5% 16.00kB/1.42MB'), ['42.5'])
        self.assertEqual(fw.PROGRESS.findall('Writing at 0x00036d07 > 3.3% 48.00kB'), ['3.3'])


class EditorFirmwareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.package_path = fw.build_package(fake_build(self.folder), self.folder / 'dist', '1.2.3', 2)
        profiles = self.folder / 'profiles.json'
        profiles.write_text(json.dumps({'default_profile': 'Main', 'profiles': {'Main': {'match': [], 'pages': {
            'First': []}}}}))
        self.controller = Mock()
        self.controller.processes.return_value = [object()]
        self.editor = Editor(profiles, self.controller, dashboard=lambda: {
            'running': True, 'device': {'connected': True, 'firmware': '1.0.0', 'protocol': 2}})
        self.flag = self.folder / 'firmware-install.local.json'
        flag_patch = patch('tessera_app.FIRMWARE_FLAG_PATH', self.flag)  # never the real tray's flag
        flag_patch.start()
        self.addCleanup(flag_patch.stop)

    def port_with(self, installed, espressif, answers):
        import host_runtime

        def identify(port):
            answer = answers.get(port)
            if isinstance(answer, Exception):
                raise answer
            return answer
        with patch.object(host_runtime, '_installed_ports', return_value=installed),                 patch.object(host_runtime, '_espressif_ports', return_value=espressif),                 patch.object(Editor, 'identify_panel', staticmethod(identify)),                 patch.dict('os.environ', {'TESSERA_PORT': 'COM4'}):
            return self.editor.firmware_port()

    def test_the_install_port_is_the_one_that_answers_not_the_default(self):
        installed = {'COM4': None, 'COM7': 'P4', 'COM9': 'P4B'}
        self.assertEqual(self.port_with(installed, ['COM7', 'COM9'], {'COM4': None, 'COM9': {'boardId': 'x'}}), 'COM9')
        self.assertEqual(self.port_with(installed, ['COM7'], {'COM4': fw.PackageError('other')}), 'COM7',
                         'a lone silent Espressif port is the blank panel')
        with self.assertRaises(fw.InstallError):  # the lone Espressif port answered as another device
            self.port_with(installed, ['COM7'], {'COM7': fw.PackageError('other board')})
        with self.assertRaises(fw.InstallError) as caught:
            self.port_with(installed, ['COM7', 'COM9'], {})
        self.assertIn('COM7', str(caught.exception))
        with self.assertRaises(fw.InstallError):
            self.port_with({'COM4': None}, [], {})  # a silent COM4 that is not an ESP32 is never flashed
        with self.assertRaises(fw.InstallError) as caught:
            self.port_with({}, [], {})
        self.assertIn('No USB port', str(caught.exception))

    def test_the_host_cannot_be_started_or_stopped_during_an_install(self):
        release = __import__('threading').Event()
        seen = []

        def identify(port):
            seen.append(self.flag.exists())
            release.wait(5)
            return {'firmwareVersion': '1.0.0'}
        with patch.object(self.editor, 'firmware_port', return_value='COM4'),                 patch.object(Editor, 'identify_panel', staticmethod(identify)),                 patch.object(fw, 'run_esptool', lambda arguments, progress: (0, '')):
            self.editor.command('firmware-install', {'package': str(self.package_path)})
            for command in ('start', 'stop'):
                with self.assertRaises(ValueError):
                    self.editor.command(command, {})
            release.set()
            job = self.wait_for_job()
        self.assertEqual(job['state'], 'done')
        self.assertEqual(seen, [True], 'the tray sees the flag while flashing')
        self.assertFalse(self.flag.exists())
        self.controller.start.assert_called_once()  # only the install's own restart

    def wait_for_job(self):
        for _ in range(200):
            if self.editor.firmware_job['state'] != 'running' and not self.editor.firmware_lock.locked():
                return self.editor.firmware_job
            time.sleep(0.02)
        self.fail('the installation did not finish')

    def test_the_update_check_asks_for_the_package_of_the_connected_board(self):
        self.editor.dashboard = lambda: {'device': {'board': 'tessera-p4-crowpanel7'}}
        with patch('tessera_app.updates.check', return_value={'latest': '9.9.9'}) as check:
            self.editor.check_updates()
        self.assertEqual(check.call_args.kwargs['board'], 'tessera-p4-crowpanel7')

    def test_the_editor_lists_packages_and_the_device_firmware(self):
        with patch.object(self.editor, 'firmware_folders', return_value=[self.package_path.parent]):
            listing = self.editor.command('firmware-list', {})
        self.assertEqual(listing['device'], {'firmware': '1.0.0', 'protocol': 2, 'board': None, 'connected': True})
        self.assertEqual([item['version'] for item in listing['packages']], ['1.2.3'])

    def test_a_panel_on_a_protocol_the_host_does_not_speak_is_marked_for_the_full_install(self):
        rejected = DeviceRejected('Firmware protocol 5 is not supported', 'protocol')
        with patch('tessera_app.PanelSerial', side_effect=rejected):
            info = Editor.identify_panel('COM4')
        self.assertEqual(info, {'boardId': fw.BOARD_ID, 'firmwareVersion': None, 'protocolUnknown': True})

    def test_a_board_that_takes_no_data_counts_as_silent_and_a_busy_port_does_not(self):
        import serial
        with patch('tessera_app.PanelSerial', side_effect=serial.SerialTimeoutException('Write timeout')):
            self.assertIsNone(Editor.identify_panel('COM4'), 'a blank board: the chip is asked next')
        with patch('tessera_app.PanelSerial', side_effect=serial.SerialException('Access is denied')),                 self.assertRaisesRegex(fw.InstallError, 'could not be opened'):
            Editor.identify_panel('COM4')
        import tesserad
        self.assertIn('no firmware yet', tesserad.port_trouble('COM4', serial.SerialTimeoutException('Write timeout')))

    def test_a_board_that_prints_at_another_speed_counts_as_silent(self):
        # An erased S3 behind a CH340 loops its ROM message at 115200; read at 921600 that is bytes without a newline.
        import panel_serial
        import types

        class Garbled:
            port, in_waiting = 'COM9', 4096

            def __init__(self):
                self.dtr = self.rts = False

            def open(self):
                pass

            def close(self):
                pass

            def reset_input_buffer(self):
                pass

            def write(self, raw):
                return len(raw)

            def read(self, size):
                return b'\x00\x80' * (size // 2)
        with patch.object(panel_serial, 'serial', types.SimpleNamespace(Serial=Garbled)), \
                patch.object(panel_serial, 'HANDSHAKE_SECONDS', 0.3):
            self.assertIsNone(Editor.identify_panel('COM9'), 'no answer: the chip is asked next')

    def test_installing_stops_the_host_flashes_and_always_restarts_it(self):
        calls = []
        with patch.object(self.editor, 'firmware_port', return_value='COM4'), \
                patch.object(Editor, 'identify_panel', staticmethod(lambda port: {'firmwareVersion': '1.0.0'})), \
                patch.object(fw, 'run_esptool', lambda arguments, progress: (calls.append(arguments) or (0, ''))):
            self.editor.command('firmware-install', {'package': str(self.package_path)})
            job = self.wait_for_job()
        self.assertEqual(job['state'], 'done')
        self.assertEqual(job['result']['installed'], '1.2.3')
        self.controller.stop.assert_called_once()
        self.controller.start.assert_called_once()
        self.assertEqual(len(calls), 1)

    def test_a_failed_install_reports_the_error_and_still_restarts_the_host(self):
        with patch.object(self.editor, 'firmware_port', return_value='COM4'), \
                patch.object(Editor, 'identify_panel', staticmethod(lambda port: {'firmwareVersion': '1.0.0'})), \
                patch.object(fw, 'run_esptool', lambda arguments, progress: (1, 'boom')):
            self.editor.command('firmware-install', {'package': str(self.package_path)})
            job = self.wait_for_job()
        self.assertEqual(job['state'], 'failed')
        self.assertIn('boom', job['error'])
        self.controller.start.assert_called_once()
        self.assertFalse(self.editor.firmware_lock.locked())

    def test_bad_requests_and_damaged_packages_are_rejected_before_the_host_is_stopped(self):
        for data in ({}, {'package': 5}, {'package': str(self.package_path), 'mode': 'wipe'},
                     {'package': str(self.package_path), 'force': 'yes'}, {'package': str(self.folder / 'no.zip')}):
            with self.assertRaises(ValueError):
                self.editor.command('firmware-install', data)
        self.controller.stop.assert_not_called()


if __name__ == '__main__':
    unittest.main()


P4_V3 = ('esptool v5.6.0\nConnected to ESP32-P4 on COM7:\nChip type:          ESP32-P4 (revision v3.2)\n'
         'Features:           Dual Core + LP Core, 400MHz\nCrystal:            40MHz\nMAC:                30:ed:a0:e1:9c:11\n'
         '\nStub flasher running.\n\nMAC:                30:ed:a0:e1:9c:11\n\nHard resetting via RTS pin...\n')


class DetectTests(unittest.TestCase):
    """A panel that does not answer: the ROM bootloader still says which chip it is."""

    def test_the_chip_and_its_revision_give_the_boards_it_can_be(self):
        runner = Mock(return_value=(0, P4_V3))
        self.assertEqual(fw.detect_chip('COM7', runner),
                         {'chip': 'esp32p4', 'revision': '3.2', 'boards': ['tessera-p4-v3']})
        self.assertIn('read-mac', runner.call_args.args[0])
        self.assertNotIn('write-flash', runner.call_args.args[0])
        older = fw.detect_chip('COM7', Mock(return_value=(0, P4_V3.replace('v3.2', 'v1.3'))))
        self.assertEqual(older['boards'], ['tessera-p4', 'tessera-p4-crowpanel7'])
        unnamed = fw.detect_chip('COM7', Mock(return_value=(0, 'Chip type:          Unknown ESP32-P4 (revision v3.2)\n')))
        self.assertEqual(unnamed['boards'], ['tessera-p4-v3'])
        s3 = fw.detect_chip('COM5', Mock(return_value=(0, 'Chip is ESP32-S3 (QFN56) (revision v0.2)\n')))
        self.assertEqual((s3['chip'], s3['revision']), ('esp32s3', '0.2'))
        self.assertEqual(s3['boards'], ['tessera-s3-ws7', 'tessera-s3-8048s070', 'tessera-s3-crowpanel7'])

    def test_a_port_without_an_esp32_or_with_another_chip_is_reported(self):
        with self.assertRaisesRegex(fw.InstallError, 'COM7 has no ESP32.*No serial data received'):
            fw.detect_chip('COM7', Mock(return_value=(2, 'A fatal error occurred: No serial data received.')))
        with self.assertRaisesRegex(fw.InstallError, 'ESP32-C6.*no Tessera firmware'):
            fw.detect_chip('COM7', Mock(return_value=(0, 'Chip type:          ESP32-C6 (QFN40) (revision v0.1)\n')))

    def test_every_board_has_a_name(self):
        self.assertEqual(set(fw.BOARD_NAMES), set(fw.BOARD_CHIPS))


class EditorDetectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        profiles = Path(self.temp.name) / 'profiles.json'
        profiles.write_text(json.dumps({'default_profile': 'Main', 'profiles': {'Main': {'match': [], 'pages': {'First': []}}}}))
        self.controller = Mock()
        self.controller.processes.return_value = [object()]
        self.editor = Editor(profiles, self.controller, dashboard=lambda: {'running': True, 'device': {'connected': False}})
        self.flag = Path(self.temp.name) / 'firmware-install.local.json'
        flag_patch = patch('tessera_app.FIRMWARE_FLAG_PATH', self.flag)
        flag_patch.start()
        self.addCleanup(flag_patch.stop)

    def detect(self, answer, esptool=(0, P4_V3)):
        with patch.object(self.editor, 'firmware_port', return_value='COM7'), \
                patch.object(Editor, 'identify_panel', staticmethod(lambda port: answer)), \
                patch.object(fw, 'run_esptool', Mock(return_value=esptool)) as runner:
            return self.editor.command('firmware-detect', {}), runner

    def test_a_silent_panel_is_asked_for_its_chip_with_the_host_stopped(self):
        found, runner = self.detect(None)
        self.assertEqual(found, {'port': 'COM7', 'chip': 'esp32p4', 'revision': '3.2', 'boards': ['tessera-p4-v3']})
        self.controller.stop.assert_called_once()
        self.controller.start.assert_called_once()
        self.assertFalse(self.flag.exists())
        self.assertFalse(self.editor.firmware_lock.locked())
        runner.assert_called_once()

    def test_a_panel_that_answers_is_not_reset(self):
        found, runner = self.detect({'boardId': 'tessera-p4-crowpanel7', 'firmwareVersion': '1.2.9'})
        self.assertEqual(found, {'port': 'COM7', 'board': 'tessera-p4-crowpanel7', 'firmware': '1.2.9', 'boards': ['tessera-p4-crowpanel7']})
        runner.assert_not_called()

    def test_a_failed_look_still_restarts_the_host_and_an_install_is_never_disturbed(self):
        with self.assertRaises(fw.InstallError):
            self.detect(None, (2, 'A fatal error occurred: No serial data received.'))
        self.controller.start.assert_called_once()
        self.assertFalse(self.editor.firmware_lock.locked())
        self.editor.firmware_lock.acquire()
        self.addCleanup(self.editor.firmware_lock.release)
        with self.assertRaisesRegex(ValueError, 'already running'):
            self.editor.command('firmware-detect', {})
        self.controller.start.assert_called_once()

    def test_the_update_check_asks_for_the_package_of_the_board_that_was_found(self):
        self.detect(None)
        with patch('tessera_app.updates.check', return_value={}) as check:
            self.editor.command('update-check', {})
        self.assertEqual(check.call_args.kwargs['board'], 'tessera-p4-v3')

    def look_at_a_lone_silent_port(self, vid, data, chip='Chip is ESP32-S3 (QFN56) (revision v0.2)\n'):
        """firmware-detect with only COM7 plugged in, whose device never answers; returns (result, esptool runs)."""
        import io
        import types
        import panel_serial

        class Silent:
            port, in_waiting = 'COM7', 0

            def __init__(self):
                self.dtr = self.rts = False

            def open(self):
                pass

            def close(self):
                pass

            def reset_input_buffer(self):
                pass

            def write(self, raw):
                return len(raw)

            def read(self, size):
                return b''
        runs = []

        def esptool(arguments, **kwargs):
            runs.append(arguments)
            return types.SimpleNamespace(stdout=io.StringIO(chip), wait=lambda: 0,
                                         kill=lambda: None)
        device = types.SimpleNamespace(device='COM7', vid=vid, serial_number=None, description='USB-SERIAL CH340 (COM7)')
        with patch('serial.tools.list_ports.comports', return_value=[device]), \
                patch.object(panel_serial, 'serial', types.SimpleNamespace(Serial=Silent)), \
                patch.object(panel_serial, 'HANDSHAKE_SECONDS', 0.1), \
                patch.object(fw.subprocess, 'Popen', esptool), \
                patch.dict('os.environ', {'TESSERA_PORT': 'COM7'}):
            return self.editor.command('firmware-detect', data), runs

    def test_a_lone_silent_usb_serial_adapter_is_restarted_only_after_the_user_says_yes(self):
        # A CH340 is also the bridge of many Arduinos and 3D printers; esptool's reset would restart a running print.
        found, runs = self.look_at_a_lone_silent_port(0x1A86, {})
        self.assertEqual(runs, [], 'esptool must not reset the device before the user agrees')
        self.assertEqual((found['port'], found['ask']), ('COM7', 'USB-SERIAL CH340 (COM7)'))
        found, runs = self.look_at_a_lone_silent_port(0x1A86, {'restart': True})
        self.assertEqual(found['boards'], ['tessera-s3-ws7', 'tessera-s3-8048s070', 'tessera-s3-crowpanel7'])
        self.assertEqual(len(runs), 1)

    def test_a_lone_silent_espressif_port_is_asked_for_its_chip_at_once(self):
        found, runs = self.look_at_a_lone_silent_port(0x303A, {})
        self.assertEqual(found['chip'], 'esp32s3')
        self.assertIn('read-mac', runs[0])

    def test_a_p4_behind_a_usb_uart_bridge_is_a_crowpanel_not_a_guition_board(self):
        # The GUITION P4 talks over the chip's own USB (VID 0x303A); the CrowPanel P4 through its CH340 UART bridge.
        v3, v1 = 'Chip is ESP32-P4 (revision v3.1)\n', 'Chip is ESP32-P4 (revision v1.3)\n'
        with self.assertRaisesRegex(fw.InstallError, 'CrowPanel.*v3'):
            self.look_at_a_lone_silent_port(0x1A86, {'restart': True}, v3)
        self.assertEqual(self.look_at_a_lone_silent_port(0x1A86, {'restart': True}, v1)[0]['boards'], ['tessera-p4-crowpanel7'])
        self.assertEqual(self.look_at_a_lone_silent_port(0x303A, {}, v3)[0]['boards'], ['tessera-p4-v3'])

    def test_the_package_list_carries_the_board_names(self):
        self.assertEqual(self.editor.command('firmware-list', {})['names']['tessera-p4-v3'], fw.BOARD_NAMES['tessera-p4-v3'])


class Board:
    """An A/B panel as ESP-IDF's bootloader runs it: an image written over USB boots on probation, the firmware
    confirms it when it answers get_info (main.cpp app_confirm), and a reset before that boots the old image again."""

    def __init__(self, running, new):
        self.running, self.new, self.previous, self.boot, self.probation = running, new, None, 7, False

    def reset(self):
        if self.probation:
            self.running, self.probation = self.previous, False
        self.boot += 1


class BoardPort:
    """The panel's serial port. On Linux opening it raises DTR and RTS, which resets a UART board (RESETS_ON_OPEN)."""
    board = None

    def __init__(self):
        self.port, self.dtr, self.rts, self.pending, self.size, self.held = None, False, False, bytearray(), 0, 0

    def open(self):
        if str(self.port).startswith('/dev/'):
            self.board.reset()

    def close(self):
        pass

    def reset_input_buffer(self):
        self.pending.clear()

    @property
    def in_waiting(self):
        return len(self.pending)

    def read(self, count):
        data, self.pending = bytes(self.pending[:count]), self.pending[count:]
        return data

    def write(self, raw):
        board = self.board
        for line in raw.decode().splitlines():
            if line == '{"cmd":"get_info"}':
                board.probation = False
                self.pending.extend((json.dumps({'type': 'info', 'boardId': 'tessera-p4', 'protocol': 2, 'ota': 1,
                                                 'firmwareVersion': board.running, 'bootId': board.boot}) + '\n').encode())
            elif line.startswith('AD_OTA_BEGIN '):
                self.size, self.held = int(line.split()[1]), 0
                self.pending.extend(b'AD_OTA_BEGIN OK\n')
            elif line.startswith('AD_OTA_DATA '):
                self.held += len(bytes.fromhex(line.split(' ', 2)[2]))
                if self.held == self.size:
                    self.pending.extend(f'AD_OTA_DATA OK {self.held}\n'.encode())
            elif line == 'AD_OTA_END':
                self.pending.extend(b'AD_OTA_END OK\n')
                board.previous, board.running, board.probation = board.running, board.new, True
                board.boot += 1  # esp_restart into the new slot
        return len(raw)


class LinuxUpdateTests(unittest.TestCase):
    def test_an_update_on_a_board_that_resets_when_the_port_opens_keeps_the_new_firmware(self):
        import types
        import panel_serial
        BoardPort.board = Board('1.0.0', '1.2.3')
        with patch.object(panel_serial, 'serial', types.SimpleNamespace(Serial=BoardPort)), \
                patch.object(panel_serial, 'RESETS_ON_OPEN', True), \
                patch.object(panel_serial, 'SETTLE_AFTER_RESET_SECONDS', 0):
            fw.serial_ota('/dev/ttyUSB0', b'\x00' * 100, lambda percent: None, version='1.2.3')
            host = panel_serial.PanelSerial('/dev/ttyUSB0', lambda *_: None)  # the host starts again after the update
        self.assertEqual(host.info['firmwareVersion'], '1.2.3')

    def test_an_update_over_the_chips_own_usb_keeps_the_new_firmware_when_the_port_goes_away(self):
        # The GUITION board (USB Serial/JTAG, /dev/ttyACM0 on Linux) drops off USB while it restarts into the new image.
        import types
        import panel_serial
        clock = Clock()
        JtagPort.board = JtagBoard('1.0.0', '1.2.3', clock)
        with patch.object(panel_serial, 'serial', types.SimpleNamespace(Serial=JtagPort)), \
                patch.object(panel_serial, 'RESETS_ON_OPEN', True), \
                patch.object(panel_serial, 'time', clock), patch.object(fw, 'time', clock):
            fw.serial_ota('/dev/ttyACM0', b'\x00' * 100, lambda percent: None, version='1.2.3')
            host = panel_serial.PanelSerial('/dev/ttyACM0', lambda *_: None)  # the host starts again after the update
        self.assertEqual(host.info['firmwareVersion'], '1.2.3')


class Clock:
    """The time of a test: a sleep, or a serial read that waits for data, moves it on at once."""
    now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class JtagBoard(Board):
    """A board on the chip's own USB. A new image also keeps itself after a minute of running (app_confirm in
    main/main.cpp), so a reset after that minute no longer brings the old one back."""

    def __init__(self, running, new, clock):
        super().__init__(running, new)
        self.clock, self.started, self.back = clock, 0.0, 0.0

    def reset(self):
        if self.clock.now - self.started >= 60:
            self.probation = False
        super().reset()
        self.started = self.clock.now


class JtagPort(BoardPort):
    """Its /dev/ttyACM0. Opening it resets the chip. When the chip restarts after AD_OTA_END its USB device goes away,
    so the open handle fails the way pyserial reports it, and the port can be opened again once the chip is back."""
    dies = None

    def open(self):
        import serial
        if self.board.clock.now < self.board.back:
            raise serial.SerialException(2, f'could not open port {self.port}: [Errno 2] No such file or directory')
        self.board.reset()

    def alive(self, error=None):
        if self.dies is not None and self.board.clock.now >= self.dies:
            raise error or OSError(5, 'Input/output error')

    def reset_input_buffer(self):
        self.alive()
        super().reset_input_buffer()

    @property
    def in_waiting(self):
        self.alive()
        return len(self.pending)

    def read(self, count):
        import serial
        if not self.pending:
            self.board.clock.sleep(0.1)  # the read timeout
        self.alive(serial.SerialException('device reports readiness to read but returned no data '
                                          '(device disconnected or multiple access on port?)'))
        return super().read(count)

    def write(self, raw):
        import serial
        self.alive(serial.SerialException('write failed: [Errno 5] Input/output error'))
        if self.dies is not None:
            return len(raw)  # it waits 300 ms for its answer to leave and then restarts: nothing more is read
        count = super().write(raw)
        if b'AD_OTA_END' in raw:
            board = self.board
            self.dies = board.started = board.clock.now + 0.3
            board.back = self.dies + 1.5  # the restarted chip is on USB again
        return count


class SerialOtaRetryTests(unittest.TestCase):
    def test_a_timed_out_upload_is_aborted_and_tried_once_more(self):
        from unittest import mock
        import panel_serial
        panels = []

        class FakePanel:
            info = {'bootId': 7, 'firmwareVersion': '1.0.0'}

            def __init__(self, port, log):
                self.sent = []
                panels.append(self)

            def ota_upload(self, data, progress):
                if len(panels) == 1:
                    raise TimeoutError('The panel did not answer AD_OTA_DATA')

            def resets_on_open(self):
                return False

            def send_line(self, line):
                self.sent.append(line)

            def close(self):
                pass
        with mock.patch.object(panel_serial, 'PanelSerial', FakePanel), mock.patch.object(fw.time, 'sleep'):
            fw.serial_ota('COM4', b'app', lambda percent: None)
        self.assertEqual(len(panels), 2)
        self.assertEqual(panels[0].sent, ['AD_OTA_ABORT'])

    def lost_end_answer(self, after):
        """Uploads seen when the answer to AD_OTA_END stays away and the panel then reports `after`."""
        from unittest import mock
        import panel_serial
        panels, percents = [], []

        class FakePanel:
            def __init__(self, port, log):
                self.info = after if panels else {'bootId': 7, 'firmwareVersion': '1.0.0'}
                self.uploads = 0
                panels.append(self)

            def ota_upload(self, data, progress):
                self.uploads += 1
                if len(panels) == 1:
                    raise TimeoutError('The panel did not answer AD_OTA_END')

            def resets_on_open(self):
                return False

            def send_line(self, line):
                pass

            def close(self):
                pass
        with mock.patch.object(panel_serial, 'PanelSerial', FakePanel), mock.patch.object(fw.time, 'sleep'):
            fw.serial_ota('COM4', b'app', percents.append, version='1.2.3')
        return [panel.uploads for panel in panels], percents

    def test_a_lost_last_answer_is_settled_by_asking_the_restarted_panel(self):
        uploads, percents = self.lost_end_answer({'bootId': 8, 'firmwareVersion': '1.2.3'})
        self.assertEqual(uploads, [1, 0], 'the panel runs the new firmware: nothing is sent twice')
        self.assertEqual(percents, [100])

    def test_a_panel_that_did_not_take_the_image_gets_it_again(self):
        for after in ({'bootId': 7, 'firmwareVersion': '1.0.0'}, {'bootId': 8, 'firmwareVersion': '1.0.0'},
                      {'bootId': 7, 'firmwareVersion': '1.2.3'}):  # not restarted, restarted into the old one, same version as before
            with self.subTest(after=after):
                self.assertEqual(self.lost_end_answer(after)[0], [1, 1])

    def test_a_second_timeout_is_reported(self):
        from unittest import mock
        import panel_serial

        class FakePanel:
            info = {'bootId': 7, 'firmwareVersion': '1.0.0'}

            def __init__(self, port, log):
                pass

            def ota_upload(self, data, progress):
                raise TimeoutError('The panel did not answer AD_OTA_DATA')

            def resets_on_open(self):
                return False

            def send_line(self, line):
                pass

            def close(self):
                pass
        with mock.patch.object(panel_serial, 'PanelSerial', FakePanel), mock.patch.object(fw.time, 'sleep'):
            with self.assertRaises(TimeoutError):
                fw.serial_ota('COM4', b'app', lambda percent: None)
