"""Dependency sync, shortcut and uninstall behaviour of the setup tool, without touching pip or the real Desktop."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import setup_tool


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
        self.assertEqual(removed, ['start with Windows', 'Desktop shortcut'])
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

    def test_a_failing_autostart_removal_is_reported_and_the_rest_continues(self):
        def broken(enabled):
            raise OSError('no access')
        removed = setup_tool.uninstall(False, lambda prompt: '', self.messages.append, self.root, self.link, broken)
        self.assertEqual(removed, ['Desktop shortcut'])
        self.assertTrue(any('autostart' in message for message in self.messages))


class CommandLineTests(unittest.TestCase):
    def test_the_launcher_script_dispatches_the_new_options_and_uses_windows_line_endings(self):
        launcher = (ROOT / 'Tessera.cmd').read_bytes()
        for option in (b'--setup', b'--uninstall', b'--diagnostics', b'setup_tool.py'):
            self.assertIn(option, launcher)
        self.assertEqual(launcher.count(b'\n'), launcher.count(b'\r\n'), 'a batch file needs CRLF line endings')


if __name__ == '__main__':
    unittest.main()
