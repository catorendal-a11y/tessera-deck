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

SUPPORTED = (1, 2)


def fake_build(folder: Path) -> Path:
    build = folder / 'build'
    (build / 'bootloader').mkdir(parents=True)
    (build / 'partition_table').mkdir()
    (build / 'bootloader/bootloader.bin').write_bytes(b'boot' * 100)
    (build / 'partition_table/partition-table.bin').write_bytes(b'part' * 50)
    (build / 'tessera.bin').write_bytes(b'app!' * 1000)
    (build / 'flasher_args.json').write_text(json.dumps({
        'flash_settings': {'flash_mode': 'dio', 'flash_size': '16MB', 'flash_freq': '80m'},
        'flash_files': {'0x2000': 'bootloader/bootloader.bin', '0x8000': 'partition_table/partition-table.bin',
                        '0x10000': 'tessera.bin'}}))
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

    def wait_for_job(self):
        for _ in range(200):
            if self.editor.firmware_job['state'] != 'running':
                return self.editor.firmware_job
            time.sleep(0.02)
        self.fail('the installation did not finish')

    def test_the_editor_lists_packages_and_the_device_firmware(self):
        with patch.object(self.editor, 'firmware_folders', return_value=[self.package_path.parent]):
            listing = self.editor.command('firmware-list', {})
        self.assertEqual(listing['device'], {'firmware': '1.0.0', 'protocol': 2, 'connected': True})
        self.assertEqual([item['version'] for item in listing['packages']], ['1.2.3'])

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
