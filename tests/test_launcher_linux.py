"""Tessera.sh: what each way of starting it runs, and the two application menu entries. A copy of the script runs next to a
fake virtual environment whose Python only writes down how it was called. Both are Linux behaviour: the paths are POSIX paths."""
from platform_marks import linux_only_module
linux_only_module(__name__)
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))

FAKE_PYTHON = '#!/bin/sh\necho "$*" >> "$(dirname "$0")/../../../calls.txt"\n'


@unittest.skipUnless(shutil.which('bash') and shutil.which('setsid'), 'needs bash and setsid')
class LauncherTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        shutil.copy(ROOT / 'Tessera.sh', self.folder / 'Tessera.sh')
        python = self.folder / 'host/.venv/bin/python'
        python.parent.mkdir(parents=True)
        python.write_text(FAKE_PYTHON)
        python.chmod(python.stat().st_mode | stat.S_IXUSR)
        self.calls = self.folder / 'calls.txt'

    def launch(self, *args):
        done = subprocess.run(['bash', str(self.folder / 'Tessera.sh'), *args], capture_output=True, text=True, timeout=30,
                              env=dict(os.environ, XDG_SESSION_TYPE='x11'))
        self.assertEqual(done.returncode, 0, done.stderr)
        deadline = time.monotonic() + 5
        while not self.calls.exists() and time.monotonic() < deadline:  # the programs start in the background
            time.sleep(0.05)
        time.sleep(0.3)
        return sorted(line for line in self.calls.read_text().splitlines() if not line.startswith('host/setup_tool.py'))

    def test_without_arguments_only_the_tray_starts(self):
        self.assertEqual(self.launch(), ['host/tessera_tray.py'])

    def test_app_starts_the_tray_and_the_editor(self):
        self.assertEqual(self.launch('--app'), ['host/tessera_app.py --editor', 'host/tessera_tray.py'])

    def test_editor_starts_only_the_editor_and_keeps_its_options(self):
        self.assertEqual(self.launch('--editor'), ['host/tessera_app.py --editor'])

    def test_the_options_after_editor_reach_the_editor(self):
        self.assertEqual(self.launch('--editor', '--port', '4711'), ['host/tessera_app.py --editor --port 4711'])


class MenuEntryTests(unittest.TestCase):
    """The two application menu entries are made from the files in linux/, which the Arch package installs as well."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        shutil.copytree(ROOT / 'host/linux', self.folder / 'host/linux')
        self.apps = self.folder / 'applications'

    def create(self):
        from platform_linux import shortcuts
        return shortcuts.create_shortcut(self.folder / 'Tessera.sh', self.apps / 'tessera-tray.desktop')

    def keys(self, name):
        text = (self.apps / name).read_text(encoding='utf-8')
        return text, dict(line.split('=', 1) for line in text.splitlines() if '=' in line)

    def test_setup_writes_a_tray_entry_and_an_editor_entry_that_start_the_launcher_of_this_folder(self):
        self.assertEqual(self.create(), self.apps / 'tessera-tray.desktop')
        launcher = str(self.folder / 'Tessera.sh')
        for name, option, title in (('tessera-tray.desktop', '--tray', 'Tessera'), ('tessera-editor.desktop', '--app', 'Tessera Editor')):
            with self.subTest(entry=name):
                _, keys = self.keys(name)
                self.assertEqual(keys['Exec'], f'"{launcher}" "{option}"')
                self.assertEqual((keys['Name'], keys['Path']), (title, str(self.folder)))
                self.assertEqual(keys['Icon'], str(self.folder / 'docs/images/logo-mark.svg'))

    def test_the_entry_of_earlier_versions_is_replaced(self):
        self.apps.mkdir()
        (self.apps / 'tessera.desktop').write_text('[Desktop Entry]\n')
        self.create()
        self.assertFalse((self.apps / 'tessera.desktop').exists())

    def test_uninstall_finds_all_of_them(self):
        from platform_linux import shortcuts
        self.apps.mkdir()
        (self.apps / 'tessera.desktop').write_text('old')
        tray = self.create()
        names = sorted(path.name for path in shortcuts.shortcut_files(tray))
        self.assertEqual(names, ['tessera-editor.desktop', 'tessera-tray.desktop', 'tessera.desktop'])

    def test_a_path_with_a_space_or_a_dollar_stays_one_word(self):
        from platform_linux import desktop_entries
        text = desktop_entries.from_template('Exec=Tessera.sh --app\nIcon=tessera\n', Path('/opt/my $dir/Tessera.sh'), Path('/opt/my $dir'))
        self.assertIn('Exec="/opt/my \\$dir/Tessera.sh" "--app"', text)

    def test_the_shipped_files_name_the_launcher_and_an_icon_a_package_can_provide(self):
        for name, option in (('tessera-tray.desktop', '--tray'), ('tessera-editor.desktop', '--app')):
            with self.subTest(file=name):
                keys = dict(line.split('=', 1) for line in (ROOT / 'host/linux' / name).read_text(encoding='utf-8').splitlines() if '=' in line)
                self.assertEqual((keys['Exec'], keys['Icon'], keys['Type'], keys['Terminal']), (f'Tessera.sh {option}', 'tessera', 'Application', 'false'))
                if shutil.which('desktop-file-validate'):
                    self.assertEqual(subprocess.run(['desktop-file-validate', str(ROOT / 'host/linux' / name)], capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
