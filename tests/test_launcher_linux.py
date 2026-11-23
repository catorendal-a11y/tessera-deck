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

FAKE_PYTHON = '#!/bin/sh\nexit 0\n'  # `setup_tool.py ensure` and the like: nothing to do
# The launcher starts the tray and the editor with `setsid nohup <python> <script> &` and does not wait for them. A fake setsid
# writes down what it was asked to start, so the test waits for that list and not for the programs themselves.
FAKE_SETSID = '#!/bin/sh\necho "$*" >> "$(dirname "$0")/../calls.txt"\n'


@unittest.skipUnless(shutil.which('bash'), 'needs bash')
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
        fake = self.folder / 'bin/setsid'
        fake.parent.mkdir()
        fake.write_text(FAKE_SETSID)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        self.calls = self.folder / 'calls.txt'

    def launch(self, *args, expect):
        """What the launcher started in the background (`expect` programs), as the script and its options."""
        done = subprocess.run(['bash', str(self.folder / 'Tessera.sh'), *args], capture_output=True, text=True, timeout=30,
                              env=dict(os.environ, XDG_SESSION_TYPE='x11', PATH=f'{self.folder / "bin"}:{os.environ["PATH"]}'))
        self.assertEqual(done.returncode, 0, done.stderr)
        deadline = time.monotonic() + 5
        while True:  # each start is written down by its own background job: wait until all of them have been
            started = self.calls.read_text().splitlines() if self.calls.exists() else []
            if len(started) >= expect or time.monotonic() > deadline:
                return sorted(line.removeprefix('nohup host/.venv/bin/python ') for line in started)
            time.sleep(0.01)

    def test_without_arguments_only_the_tray_starts(self):
        self.assertEqual(self.launch(expect=1), ['host/tessera_tray.py'])

    def test_app_starts_the_tray_and_the_editor(self):
        self.assertEqual(self.launch('--app', expect=2), ['host/tessera_app.py --editor', 'host/tessera_tray.py'])

    def test_editor_starts_only_the_editor_and_keeps_its_options(self):
        self.assertEqual(self.launch('--editor', expect=1), ['host/tessera_app.py --editor'])

    def test_the_options_after_editor_reach_the_editor(self):
        self.assertEqual(self.launch('--editor', '--port', '4711', expect=1), ['host/tessera_app.py --editor --port 4711'])

    def notes(self, tools, **env):
        """What the launcher says about the desktop tools when only `tools` ({name: exit status}) are on the PATH."""
        bin_ = self.folder / 'bin'
        for old in bin_.iterdir():
            if old.name != 'setsid':
                old.unlink()  # each call has only the tools it names
        for name in ('dirname', 'readlink'):
            (bin_ / name).symlink_to(shutil.which(name))
        for name, status in tools.items():
            fake = bin_ / name
            fake.write_text(f'#!/bin/sh\nexit {status}\n')
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        done = subprocess.run([shutil.which('bash'), str(self.folder / 'Tessera.sh'), '--tray'], capture_output=True,
                              text=True, timeout=30, env={'PATH': str(self.folder / 'bin'), 'HOME': str(self.folder), **env})
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stderr

    def test_a_plasma_wayland_session_with_its_tools_needs_no_note(self):
        self.assertEqual(self.notes({'ydotool': 0, 'kdotool': 0, 'wl-copy': 0},
                                    XDG_SESSION_TYPE='wayland', XDG_CURRENT_DESKTOP='KDE'), '')

    def test_a_wayland_session_names_what_is_missing(self):
        self.assertIn('ydotool', self.notes({}, XDG_SESSION_TYPE='wayland', XDG_CURRENT_DESKTOP='KDE'))
        self.assertIn('ydotoold is not running', self.notes({'ydotool': 2, 'kdotool': 0, 'wl-copy': 0},
                                                            XDG_SESSION_TYPE='wayland', XDG_CURRENT_DESKTOP='KDE'))

    def test_kdotool_is_asked_for_on_plasma_and_other_desktops_are_told_what_works(self):
        self.assertIn('kdotool not found', self.notes({'ydotool': 0, 'wl-copy': 0}, XDG_SESSION_TYPE='wayland',
                                                      XDG_CURRENT_DESKTOP='KDE'))
        self.assertIn('need KDE Plasma', self.notes({'ydotool': 0, 'wl-copy': 0}, XDG_SESSION_TYPE='wayland',
                                                    XDG_CURRENT_DESKTOP='sway'))

    def test_gnome_is_told_about_its_extension_until_it_is_installed(self):
        tools = {'ydotool': 0, 'wl-copy': 0}
        self.assertIn('--gnome-extension', self.notes(tools, XDG_SESSION_TYPE='wayland', XDG_CURRENT_DESKTOP='ubuntu:GNOME'))
        (self.folder / '.local/share/gnome-shell/extensions/tessera-windows@tessera').mkdir(parents=True)
        self.assertEqual(self.notes(tools, XDG_SESSION_TYPE='wayland', XDG_CURRENT_DESKTOP='ubuntu:GNOME'), '')

    def test_installing_the_gnome_extension_warns_on_a_gnome_other_than_the_one_it_is_marked_for(self):
        # the extension's metadata.json lists GNOME 51 only; another Shell version refuses to enable it
        shutil.copytree(ROOT / 'host/linux/gnome-extension', self.folder / 'host/linux/gnome-extension')
        shell = self.folder / 'bin/gnome-shell'
        for version, warned in (('50.1', True), ('51.0', False), ('52.0', True)):
            shell.write_text(f'#!/bin/sh\necho "GNOME Shell {version}"\n')
            shell.chmod(shell.stat().st_mode | stat.S_IXUSR)
            done = subprocess.run(['bash', str(self.folder / 'Tessera.sh'), '--gnome-extension'], capture_output=True, text=True,
                                  timeout=30, env=dict(os.environ, XDG_DATA_HOME=str(self.folder / 'data'),
                                                       PATH=f'{self.folder / "bin"}:{os.environ["PATH"]}'))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual('GNOME 51' in done.stderr, warned, done.stderr)

    def test_without_ydotool_the_portal_is_named(self):
        self.assertIn('RemoteDesktop portal', self.notes({'kdotool': 0, 'wl-copy': 0}, XDG_SESSION_TYPE='wayland',
                                                         XDG_CURRENT_DESKTOP='KDE'))

    def test_an_x11_session_still_asks_for_xdotool_and_xclip(self):
        self.assertIn('xdotool xclip not found', self.notes({}, XDG_SESSION_TYPE='x11'))


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
