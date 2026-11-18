"""Updating the program from the editor: the release's host zip is checked against SHA256SUMS and unpacked over the
program folder. What the user made stays, and nothing outside the folder is written."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import updates
from tessera_app import Editor
from test_updates import router

TAG = 'v9.9.9'
NAME = f'tessera-host-{TAG}.zip'
PROGRAM = {'VERSION': '9.9.9\n', 'host/tesserad.py': 'new host\n', 'host/editor/app.js': 'new editor\n',
           'firmware/tessera-firmware-9.9.9.zip': 'firmware'}


def host_zip(files=None, top='tessera-v9.9.9/'):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        for name, text in (PROGRAM if files is None else files).items():
            archive.writestr(top + name, text)
    return data.getvalue()


def release(package):
    return {'tag_name': TAG, 'html_url': 'https://github.com/catorendal-a11y/tessera-deck/releases/tag/' + TAG, 'assets': [
        {'name': NAME, 'size': len(package), 'browser_download_url': f'https://github.com/r/{NAME}'},
        {'name': 'SHA256SUMS', 'size': 100, 'browser_download_url': 'https://github.com/r/SHA256SUMS'}]}


class Case(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'tessera'
        (self.root / 'host').mkdir(parents=True)
        self.package = host_zip()
        self.info = updates.check('1.0.0', router({updates.RELEASE_API: json.dumps(release(self.package))}))

    def routes(self, sums=None):
        sums = f'{hashlib.sha256(self.package).hexdigest()}  {NAME}\n' if sums is None else sums
        return router({f'https://github.com/r/{NAME}': self.package, 'https://github.com/r/SHA256SUMS': sums})

    def saved(self, package=None):
        path = self.root.parent / NAME
        path.write_bytes(self.package if package is None else package)
        return path


class DownloadTests(Case):
    def test_the_check_names_the_program_file_of_the_release(self):
        self.assertEqual(self.info['host']['name'], NAME)

    def test_a_matching_checksum_saves_the_program_file(self):
        target = updates.download_host(self.info, self.root.parent / 'download', self.routes())
        self.assertEqual(target.read_bytes(), self.package)

    def test_a_program_file_that_does_not_match_its_checksum_is_not_saved(self):
        with self.assertRaises(ValueError) as raised:
            updates.download_host(self.info, self.root.parent / 'download', self.routes(sums=f'{"0" * 64}  {NAME}\n'))
        self.assertIn('checksum', str(raised.exception))
        self.assertFalse((self.root.parent / 'download' / NAME).exists())


class InstallTests(Case):
    def test_the_program_is_replaced_and_what_the_user_made_stays(self):
        mine = {'host/profiles.json': 'my keys', 'host/state.local.json': 'my counters', 'host/assets/icon.png': 'my icon',
                'host/backups/profiles-20260101-000000.json': 'my backup'}
        for name, text in dict(mine, **{'host/tesserad.py': 'old host\n'}).items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text(text, encoding='utf-8')
        # a release never holds user data; a file that claims to is not written over the user's own
        package = host_zip(dict(PROGRAM, **{name: 'not yours' for name in mine}, **{'host/other.local.json': 'not yours'}))
        written = updates.install_host(self.saved(package), self.root)
        self.assertEqual(written, len(PROGRAM))
        for name, text in PROGRAM.items():
            self.assertEqual((self.root / name).read_text(encoding='utf-8'), text, name)
        for name, text in mine.items():
            self.assertEqual((self.root / name).read_text(encoding='utf-8'), text, name)
        self.assertFalse((self.root / 'host/other.local.json').exists())
        self.assertEqual([path.name for path in self.root.rglob('*.new')], [])

    def test_a_source_checkout_is_left_to_git(self):
        (self.root / '.git').mkdir()
        with self.assertRaises(ValueError) as raised:
            updates.install_host(self.saved(), self.root)
        self.assertIn('git pull', str(raised.exception))
        self.assertFalse((self.root / 'VERSION').exists())

    def test_a_file_that_would_land_outside_the_folder_stops_the_update_before_anything_is_written(self):
        for bad in ('../outside.txt', 'host/../../outside.txt', 'C:/outside.txt'):
            with self.subTest(bad), self.assertRaises(ValueError):
                updates.install_host(self.saved(host_zip(dict(PROGRAM, **{bad: 'x'}))), self.root)
            self.assertFalse((self.root / 'VERSION').exists(), 'nothing is written when one name is refused')
        self.assertFalse((self.root.parent / 'outside.txt').exists())

    def test_a_zip_that_is_not_the_program_is_refused(self):
        with self.assertRaises(ValueError) as raised:
            updates.install_host(self.saved(host_zip({'readme.txt': 'hello'})), self.root)
        self.assertIn('not a Tessera', str(raised.exception))


class EditorTests(Case):
    def editor(self):
        path = self.root / 'host/profiles.json'
        path.write_text(json.dumps({'default_profile': 'Main', 'profiles': {'Main': {'match': [], 'pages': {'First': []}}}}))
        return Editor(path, dashboard=lambda: {'running': False, 'device': {}})

    def test_the_update_needs_a_check_that_found_a_newer_version(self):
        editor = self.editor()
        with self.assertRaises(ValueError) as raised:
            editor.install_host_update()
        self.assertIn('Check for updates first', str(raised.exception))
        editor.last_release = dict(self.info, newer=False)
        with self.assertRaises(ValueError) as raised:
            editor.install_host_update()
        self.assertIn('newest', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
