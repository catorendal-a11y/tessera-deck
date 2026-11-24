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
import action_runner
import config_store
import make_linux_defaults
import tesserad

LINUX = json.loads((ROOT / 'host/profiles.default.linux.json').read_text(encoding='utf-8'))
MISSING = 'None of these programs is installed: alpha, beta. Install one with your package manager.'


def actions():
    for profile in LINUX['profiles'].values():
        for page in profile['pages'].values():
            for button in page:
                yield from button.get('actions', [])
                for state in button.get('states', []):
                    yield from state.get('actions', [])


def shell_commands(profile, page, label):
    """The shell commands of the key with this label."""
    return [action['command'] for button in LINUX['profiles'][profile]['pages'][page] if button.get('label') == label
            for action in button.get('actions', []) if action.get('type') == 'shell']


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
            self.assertIn("echo 'None of these programs is installed: ", command)
            self.assertIn('>&2; exit 1', command)
        # 'gamma' is an argument of beta, not a program; each program is named once
        self.assertIn(f"echo '{MISSING}' >&2", make_linux_defaults.launch('alpha', 'beta gamma', 'beta delta')['command'])
        for command in (make_linux_defaults.TERMINAL['command'], make_linux_defaults.in_terminal('claude -c')['command']):
            message = command.split("echo '")[1].split("' >&2")[0]
            self.assertLessEqual(len(message), action_runner.STDERR_TAIL, 'the key error shows only this much of it')

    @linux_only
    @unittest.skipUnless(shutil.which('bash'), 'needs bash')
    def test_with_no_program_installed_the_command_fails_with_a_message(self):
        with tempfile.TemporaryDirectory() as empty:
            done = subprocess.run(['bash', '-c', make_linux_defaults.launch('alpha', 'beta gamma')['command']],
                                  capture_output=True, text=True, env={'PATH': empty, 'HOME': empty})
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stderr.strip(), MISSING)

    def test_the_keys_have_a_candidate_for_plasma_6_and_for_stock_gnome_and_kde(self):
        # stock GNOME and KDE do not install pavucontrol, and Plasma 6 has no ksysguard
        mixers = ('pavucontrol', 'pavucontrol-qt', 'gnome-control-center sound', 'systemsettings kcm_pulseaudio')
        wanted = {('tools', 'System monitor'): ('plasma-systemmonitor',), ('audio', 'Bluetooth'): ('systemsettings kcm_bluetooth',),
                  ('audio', 'Volume mixer'): mixers, ('audio', 'Audio devices'): mixers}
        for (page, label), candidates in wanted.items():
            command, = shell_commands('main', page, label)
            for candidate in candidates:
                self.assertIn(f'exec setsid -f {candidate})', command, label)

    def test_the_terminal_keys_find_the_default_terminal_of_fedora_gnome_mate_lxqt_and_cosmic(self):
        # Fedora 41 and later ship Ptyxis and no gnome-terminal or x-terminal-emulator
        terminal, = shell_commands('main', 'main', 'Terminal')
        agent, = shell_commands('Claude Code', 'main', 'Continue')
        self.assertIn('exec setsid -f ptyxis --new-window)', terminal)
        self.assertIn('exec setsid -f ptyxis -- claude -c)', agent)
        for name, flag in (('kgx', '--'), ('mate-terminal', '-x'), ('qterminal', '-e'), ('cosmic-term', '-e')):
            self.assertIn(f'exec setsid -f {name})', terminal)
            self.assertIn(f'exec setsid -f {name} {flag} claude -c)', agent)

    def test_the_agent_profiles_start_their_tool_in_a_terminal(self):
        commands = [action['command'] for action in actions() if action.get('type') == 'shell']
        for tool in ('claude -c', 'claude -r', 'codex resume --last'):
            self.assertTrue(any(command.endswith(f'-e {tool}) || ') or f'-e {tool})' in command for command in commands), tool)


if __name__ == '__main__':
    unittest.main()
