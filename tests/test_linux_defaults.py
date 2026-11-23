"""The Linux default profile: it is valid, its shell commands parse, no Windows launcher is left, and it is up to date."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
sys.path.insert(0, str(ROOT / 'tools'))
from platform_marks import linux_only  # noqa: E402
import config_store
import make_linux_defaults
import tesserad

LINUX = json.loads((ROOT / 'host/profiles.default.linux.json').read_text(encoding='utf-8'))


def actions():
    for profile in LINUX['profiles'].values():
        for page in profile['pages'].values():
            for button in page:
                yield from button.get('actions', [])
                for state in button.get('states', []):
                    yield from state.get('actions', [])


class LinuxDefaultTests(unittest.TestCase):
    def test_it_is_a_valid_configuration(self):
        tesserad.validate_config(config_store.migrate(json.loads(json.dumps(LINUX))))

    def test_it_is_what_the_generator_makes_from_the_windows_default(self):
        windows = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        self.assertEqual(make_linux_defaults.convert(windows), LINUX, 'run python tools/make_linux_defaults.py')

    def test_no_windows_launcher_or_variable_is_left_in_a_command(self):
        for action in actions():
            text = json.dumps(action)
            for leftover in ('wt.exe', 'cmd.exe', '%CD%', '%LOCALAPPDATA%', 'ms-settings', 'sndvol', 'mmsys.cpl', 'explorer.exe'):
                self.assertNotIn(leftover, text)

    @linux_only  # bash on a Windows PC is often the WSL stub, which cannot run these commands
    @unittest.skipUnless(shutil.which('bash'), 'needs bash')
    def test_every_shell_command_is_valid_shell(self):
        commands = [action['command'] for action in actions() if action.get('type') == 'shell']
        self.assertGreater(len(commands), 10)
        for command in commands:
            done = subprocess.run(['bash', '-n', '-c', command], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, f'{command}\n{done.stderr}')

    def test_a_program_that_is_not_installed_is_named_in_the_error(self):
        # the key's error shows the tail of stderr; with an empty one the user only reads "exited with code 1"
        for command in (make_linux_defaults.launch('alpha', 'beta gamma')['command'],
                        make_linux_defaults.in_terminal('claude -c')['command']):
            self.assertIn("echo 'none of: ", command)
            self.assertIn('>&2; exit 1', command)
        self.assertIn('none of: alpha, beta gamma is installed', make_linux_defaults.launch('alpha', 'beta gamma')['command'])

    @linux_only
    @unittest.skipUnless(shutil.which('bash'), 'needs bash')
    def test_with_no_program_installed_the_command_fails_with_a_message(self):
        with tempfile.TemporaryDirectory() as empty:
            done = subprocess.run(['bash', '-c', make_linux_defaults.launch('alpha', 'beta gamma')['command']],
                                  capture_output=True, text=True, env={'PATH': empty, 'HOME': empty})
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stderr.strip(), 'none of: alpha, beta gamma is installed')

    def test_the_keys_have_a_candidate_for_plasma_6_and_for_stock_gnome_and_kde(self):
        everything = json.dumps(LINUX)
        for candidate in ('plasma-systemmonitor', 'systemsettings kcm_bluetooth', 'systemsettings kcm_pulseaudio'):
            self.assertIn(candidate, everything)

    def test_the_agent_profiles_start_their_tool_in_a_terminal(self):
        commands = [action['command'] for action in actions() if action.get('type') == 'shell']
        for tool in ('claude -c', 'claude -r', 'codex resume --last'):
            self.assertTrue(any(command.endswith(f'-e {tool}) || ') or f'-e {tool})' in command for command in commands), tool)


if __name__ == '__main__':
    unittest.main()
