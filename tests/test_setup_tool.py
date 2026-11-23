"""Dependency sync, shortcut and uninstall behaviour of the setup tool, without touching pip or the real Desktop."""
import os
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import setup_tool

AUTOSTART = 'start with Windows' if os.name == 'nt' else 'start with the desktop'  # what uninstall reports
SHORTCUT = 'Desktop shortcut' if os.name == 'nt' else 'application menu entry'


class EnsureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.requirements = self.folder / 'requirements.txt'
        self.requirements.write_text('pyserial==3.5\n')
        self.hash_file = self.folder / 'venv' / 'requirements.sha256'
        self.messages, self.installs = [], []

    def ensure(self, works=True, code=0):
        def install(command):
            self.installs.append(command)
            return code
        return setup_tool.ensure('python', lambda python: works, install, self.hash_file, self.requirements,
                                 self.messages.append)

    def test_a_fresh_environment_installs_once_and_remembers_the_requirements(self):
        self.assertTrue(self.ensure(works=False))
        self.assertEqual(len(self.installs), 1)
        self.assertIn('-r', self.installs[0])
        self.assertEqual(self.hash_file.read_text().strip(), setup_tool.requirements_hash(self.requirements))
        self.assertTrue(self.ensure())
        self.assertEqual(len(self.installs), 1, 'nothing changed, so nothing is installed again')

    def test_changed_requirements_trigger_a_new_install(self):
        self.ensure(works=False)
        self.requirements.write_text('pyserial==3.5\npsutil==7.0.0\n')
        self.assertTrue(self.ensure())
        self.assertEqual(len(self.installs), 2)
        self.assertTrue(any('changed' in message for message in self.messages))

    def test_a_missing_package_is_repaired_even_when_the_hash_matches(self):
        self.ensure(works=False)
        self.assertTrue(self.ensure(works=False))
        self.assertEqual(len(self.installs), 2)

    def test_a_failed_install_is_explained_and_does_not_record_success(self):
        self.assertFalse(self.ensure(works=False, code=1))
        self.assertFalse(self.hash_file.exists())
        self.assertTrue(any('internet connection' in message for message in self.messages))

    def test_the_decision_function(self):
        self.assertIsNone(setup_tool.needs_install('a', 'a', True))
        self.assertIn('changed', setup_tool.needs_install('a', 'b', True))
        self.assertIn('missing', setup_tool.needs_install('a', 'a', False))
        self.assertIn('changed', setup_tool.needs_install(None, 'a', True))

    def test_a_lock_file_is_installed_with_its_hashes_and_its_changes_count(self):
        lock = self.requirements.with_suffix('.lock')
        lock.write_text('pyserial==3.5 --hash=sha256:aa\n')
        self.assertTrue(self.ensure(works=False))
        self.assertIn('--require-hashes', self.installs[0])
        self.assertEqual(self.installs[0][-1], str(lock))
        lock.write_text('pyserial==3.5 --hash=sha256:bb\n')
        self.assertTrue(self.ensure())
        self.assertEqual(len(self.installs), 2, 'a new lock file is installed again')

    def test_the_real_lock_file_pins_every_requirement(self):
        import re
        names = lambda text: {re.split(r'[<>=!;\s\[]', line, maxsplit=1)[0].lower().replace('_', '-').replace('.', '-')
                              for line in text.splitlines() if line and line[0].isalpha()}
        self.assertTrue(setup_tool.LOCK.is_file())
        required = names(setup_tool.REQUIREMENTS.read_text(encoding='utf-8'))
        locked = names(setup_tool.LOCK.read_text(encoding='utf-8'))
        self.assertLessEqual(required, locked, 'run pip-compile --generate-hashes again (see CONTRIBUTING.md)')
        lock_text = setup_tool.LOCK.read_text(encoding='utf-8').lower()
        for pin in re.findall(r'^([\w.-]+==[\w.!]+)\s*$', setup_tool.REQUIREMENTS.read_text(encoding='utf-8'), re.M):
            self.assertIn(pin.lower() + ' ', lock_text, f'{pin} changed: run pip-compile again (see CONTRIBUTING.md)')

    def test_the_real_requirements_file_has_a_stable_hash(self):
        self.assertEqual(setup_tool.requirements_hash(), setup_tool.requirements_hash())
        self.assertEqual(len(setup_tool.requirements_hash()), 64)


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'host/assets').mkdir(parents=True)
        (self.root / 'host/backups').mkdir()
        for relative in ('host/profiles.json', 'host/state.local.json', 'host/assets/icon.png', 'host/backups/a.json',
                         'host/tessera_app.py'):
            (self.root / relative).write_text('x')
        self.link = self.root / 'Tessera.lnk'
        self.link.write_text('link')
        self.removed_autostart = []
        self.messages = []

    def run_uninstall(self, purge=False, answer='no'):
        return setup_tool.uninstall(purge, lambda prompt: answer, self.messages.append, self.root, self.link,
                                    self.removed_autostart.append)

    def test_a_plain_uninstall_removes_the_entries_but_keeps_user_data(self):
        removed = self.run_uninstall()
        self.assertEqual(removed, [AUTOSTART, SHORTCUT])
        self.assertEqual(self.removed_autostart, [False])
        self.assertFalse(self.link.exists())
        self.assertTrue((self.root / 'host/profiles.json').exists())
        self.assertTrue(any('kept' in message for message in self.messages))

    def test_purge_needs_the_exact_confirmation_word(self):
        for answer in ('', 'yes', 'y', 'YES please'):
            self.run_uninstall(purge=True, answer=answer)
            self.assertTrue((self.root / 'host/profiles.json').exists(), answer)

    def test_a_confirmed_purge_deletes_user_data_but_never_the_program(self):
        removed = self.run_uninstall(purge=True, answer='YES')
        self.assertIn('your data', removed)
        for relative in ('host/profiles.json', 'host/state.local.json', 'host/assets', 'host/backups'):
            self.assertFalse((self.root / relative).exists(), relative)
        self.assertTrue((self.root / 'host/tessera_app.py').exists())

    def test_a_purge_deletes_every_local_state_log_and_trigger_file(self):
        names = ('deck.local.log', 'deck.local.log.1', 'triggers.local.json', 'tray-first-run.local.json', 'update-check.local.json')
        for name in names:
            (self.root / 'host' / name).write_text('x')
        self.run_uninstall(purge=True, answer='YES')
        for name in names:
            self.assertFalse((self.root / 'host' / name).exists(), name)
        self.assertTrue((self.root / 'host/tessera_app.py').exists())

    def test_uninstall_does_not_claim_an_autostart_entry_that_was_not_there(self):
        import deck_control
        gone = self.root / 'no-such-entry'
        with patch.object(deck_control, 'startup_script_path', return_value=gone),                 patch.object(deck_control, 'set_autostart') as turn_off:
            removed = setup_tool.uninstall(False, lambda prompt: '', self.messages.append, self.root, self.link)
        turn_off.assert_not_called()  # nothing of this folder starts at sign-in
        self.assertEqual(removed, [SHORTCUT])

    def test_uninstall_leaves_the_autostart_entry_of_another_copy(self):
        import deck_control
        from venv_paths import venv_python
        copy = self.root / 'other copy'
        for python in (venv_python(copy), venv_python(copy, windowless=True)):
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text('')
        entry = deck_control.startup_script_path(self.root / 'appdata')  # a startup folder of its own, not the real one
        setup_tool.load('autostart').enable(entry, copy)  # what that copy writes
        written = entry.read_bytes()
        with patch.object(deck_control, 'startup_script_path', return_value=entry):
            removed = setup_tool.uninstall(False, lambda prompt: '', self.messages.append, self.root, self.link)
        self.assertTrue(entry.exists(), "the other copy's autostart entry was deleted")
        self.assertEqual(entry.read_bytes(), written)
        self.assertEqual(removed, [SHORTCUT])

    def test_uninstall_says_when_the_elevated_sensors_task_is_still_there(self):
        # --sensors makes a sign-in task that runs Libre Hardware Monitor as administrator; deleting the folder
        # does not remove it, so the user is told to run --sensors-off first
        setup_tool.uninstall(False, lambda prompt: '', self.messages.append, self.root, self.link,
                             self.removed_autostart.append, lambda: True)
        text = ' '.join(self.messages)
        self.assertIn('--sensors-off', text)
        self.assertIn('administrator', text)

    def test_uninstall_stays_quiet_about_sensors_when_there_is_no_task(self):
        setup_tool.uninstall(False, lambda prompt: '', self.messages.append, self.root, self.link,
                             self.removed_autostart.append, lambda: False)
        self.assertNotIn('--sensors-off', ' '.join(self.messages))

    def test_a_purge_also_deletes_every_copy_of_the_profiles(self):
        copies = ('host/profiles-unreadable.local.json', 'host/profiles-unreadable-1.local.json',
                  'host/profiles-previous.local.json', 'host/profiles.json.abc123.tmp')
        for relative in copies:
            (self.root / relative).write_text('x')
        self.assertIn('your data', self.run_uninstall(purge=True, answer='YES'))
        for relative in copies:
            self.assertFalse((self.root / relative).exists(), relative)

    def test_a_purge_that_cannot_delete_everything_says_so(self):
        unlink = Path.unlink
        uninstall = setup_tool.uninstall

        def locked(path, *args, **kwargs):  # the host still has the file open
            if path.name == 'profiles.json':
                raise PermissionError(13, 'Access is denied', str(path))
            return unlink(path, *args, **kwargs)
        with patch('pathlib.Path.unlink', autospec=True, side_effect=locked), \
                patch.object(setup_tool, 'uninstall', lambda purge, **_: uninstall(
                    purge, lambda prompt: 'YES', self.messages.append, self.root, self.link,
                    self.removed_autostart.append)), \
                patch('builtins.print') as printed:
            self.assertEqual(setup_tool.main(['uninstall', '--purge']), 1)
        printed.assert_called_once()
        self.assertTrue((self.root / 'host/profiles.json').exists())
        self.assertFalse((self.root / 'host/state.local.json').exists(), 'the rest is still deleted')
        problem = next(message for message in self.messages if message.startswith('Could not delete'))
        self.assertIn('profiles.json', problem)
        self.assertIn('Access is denied', problem)
        self.assertNotIn('your data', self.messages[-1])

    def test_a_failing_autostart_removal_is_reported_and_the_rest_continues(self):
        def broken(enabled):
            raise OSError('no access')
        removed = setup_tool.uninstall(False, lambda prompt: '', self.messages.append, self.root, self.link, broken)
        self.assertEqual(removed, [SHORTCUT])
        self.assertTrue(any('autostart' in message for message in self.messages))


class DiagnosticsTests(unittest.TestCase):
    def test_a_broken_profile_file_still_gives_a_bundle(self):
        import diagnostics
        with tempfile.TemporaryDirectory() as folder:
            target = diagnostics.build(Path(folder), None, {}, '1.0', Path(folder) / 'none.log')
            with zipfile.ZipFile(target) as archive:
                report = json.loads(archive.read('report.json'))
        self.assertEqual(report['configuration'], {'readable': False})
        with patch('tesserad.Daemon.load_profiles', side_effect=ValueError('Unknown page: Work')), \
                patch('deck_control.Controller'), patch('diagnostics.build') as build:
            self.assertIs(setup_tool.diagnostics(), build.return_value)
        self.assertIsNone(build.call_args.args[1])


class CommandLineTests(unittest.TestCase):
    def test_the_launcher_script_dispatches_the_new_options_and_uses_windows_line_endings(self):
        launcher = (ROOT / 'Tessera.cmd').read_bytes()
        for option in (b'--setup', b'--uninstall', b'--diagnostics', b'setup_tool.py'):
            self.assertIn(option, launcher)
        self.assertEqual(launcher.count(b'\n'), launcher.count(b'\r\n'), 'a batch file needs CRLF line endings')



@unittest.skipUnless(sys.platform == 'win32', 'Windows shortcuts')
class ShortcutTests(unittest.TestCase):
    def test_the_shortcut_is_written_with_its_target_and_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            link = Path(folder) / 'Tessera.lnk'
            target = Path(folder) / 'my app' / 'Tessera.cmd'
            target.parent.mkdir()
            setup_tool.create_shortcut(target, link)
            import tessera_app
            self.assertEqual(Path(tessera_app.shortcut_target(link)), target)


if __name__ == '__main__':
    unittest.main()
