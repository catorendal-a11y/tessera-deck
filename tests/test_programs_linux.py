"""Linux program list: .desktop parsing, process names from Exec lines, icon lookup and launching."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_marks import linux_only_module
linux_only_module(__name__)
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from platform_linux import desktop_entries, programs


def write(folder, name, **fields):
    lines = ['[Desktop Entry]'] + [f'{key}={value}' for key, value in dict({'Type': 'Application'}, **fields).items()]
    path = Path(folder, 'applications', name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


class ScanTests(unittest.TestCase):
    def test_the_menu_is_scanned_with_the_users_entries_first_and_hidden_ones_left_out(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as system:
            write(home, 'mine.desktop', Name='Editor', Exec='myeditor %F')
            write(system, 'editor.desktop', Name='Editor', Exec='othereditor')
            write(system, 'hidden.desktop', Name='Helper', Exec='helper', NoDisplay='true')
            write(system, 'doc.desktop', Name='Editor Documentation', Exec='docs')
            write(system, 'link.desktop', Name='Site', Type='Link', URL='https://x')
            write(system, 'zeta.desktop', Name='Zeta', Exec='zeta')
            found = programs.scan({'XDG_DATA_HOME': home, 'XDG_DATA_DIRS': system})
        self.assertEqual([item['name'] for item in found], ['Editor', 'Zeta'])
        self.assertTrue(found[0]['target'].startswith(home))

    def test_a_broken_file_is_skipped(self):
        with tempfile.TemporaryDirectory() as home:
            path = write(home, 'bad.desktop', Name='Bad', Exec='bad')
            path.write_bytes(b'\xff\xfe not a desktop file')
            self.assertEqual(programs.scan({'XDG_DATA_HOME': home, 'XDG_DATA_DIRS': '/nonexistent'}), [])

    def test_the_name_in_the_users_language_is_used(self):
        with tempfile.TemporaryDirectory() as home, patch.dict('os.environ', {'LANG': 'de_DE.UTF-8'}):
            write(home, 'a.desktop', Name='Files', **{'Name[de]': 'Dateien'}, Exec='nemo')
            self.assertEqual(programs.scan({'XDG_DATA_HOME': home, 'XDG_DATA_DIRS': '/nonexistent'})[0]['name'], 'Dateien')


class ProcessNameTests(unittest.TestCase):
    def test_the_program_behind_an_exec_line(self):
        for line, expected in (('firefox %u', 'firefox'), ('/usr/bin/nemo %U', 'nemo'), ('env GDK_BACKEND=x11 /opt/App/app --flag', 'app'),
                               ('sh -c "exec spotify"', 'spotify'),
                               ('flatpak run --branch=stable org.mozilla.firefox @@u %u @@', 'firefox'),
                               ('"/opt/My App/start" --x', 'start'), ('', ''), ('unterminated "quote', '')):
            self.assertEqual(programs.process_name(line), expected, line)


class IconTests(unittest.TestCase):
    def test_an_absolute_icon_path_is_used_as_it_is(self):
        with tempfile.NamedTemporaryFile(suffix='.png') as icon:
            self.assertEqual(programs.icon_file(icon.name), Path(icon.name))
        self.assertIsNone(programs.icon_file('/no/such/icon.png'))
        self.assertIsNone(programs.icon_file(''))

    def test_a_theme_icon_prefers_the_largest_png(self):
        with tempfile.TemporaryDirectory() as home:
            for size in ('48x48', '256x256'):
                folder = Path(home, 'icons', 'hicolor', size, 'apps')
                folder.mkdir(parents=True)
                (folder / 'demo.png').write_bytes(b'png')
            scalable = Path(home, 'icons', 'hicolor', 'scalable', 'apps')
            scalable.mkdir(parents=True)
            (scalable / 'demo.svg').write_bytes(b'<svg/>')
            found = programs.icon_file('demo', {'XDG_DATA_HOME': home, 'XDG_DATA_DIRS': '/nonexistent'})
        self.assertEqual(found.parts[-3], '256x256')


class LaunchTests(unittest.TestCase):
    def test_a_menu_entry_is_started_with_gio_and_an_address_with_xdg_open(self):
        with tempfile.TemporaryDirectory() as home, patch('shutil.which', side_effect=lambda name: '/usr/bin/' + name), \
                patch('subprocess.Popen') as popen:
            entry = write(home, 'x.desktop', Name='X', Exec='x')
            programs.launch(str(entry))
            programs.launch('https://example.com/a b')
            programs.launch('~/notes.txt')
        commands = [call.args[0] for call in popen.call_args_list]
        self.assertEqual(commands[0], ['gio', 'launch', str(entry)])
        self.assertEqual(commands[1], ['xdg-open', 'https://example.com/a b'])
        self.assertEqual(commands[2][0], 'xdg-open')
        self.assertTrue(commands[2][1].endswith('/notes.txt') and not commands[2][1].startswith('~'))
        self.assertTrue(all(call.kwargs['start_new_session'] for call in popen.call_args_list))


class DescribeTests(unittest.TestCase):
    def test_a_menu_entry_is_described_by_its_name_and_process(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = write(directory, 'fox.desktop', Name='Fox', Exec='/usr/bin/fox %u')
            self.assertEqual(programs.describe(str(entry)), {'name': 'Fox', 'process': 'fox'})

    def test_anything_else_is_refused(self):
        for target in ('/usr/bin/fox', '/no/such.desktop'):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'application menu'):
                programs.describe(target)

    def test_only_the_editor_window_is_raised_and_a_shortcut_is_its_own_target(self):
        # the editor's own window is tested in test_editor_window_linux.py
        from platform_linux import editor_window, shell
        self.assertFalse(editor_window.activate_window(1))  # a process without the window helper is never raised
        self.assertEqual(shell.shortcut_target(Path('/a/b.lnk')), '/a/b.lnk')


class AutostartTests(unittest.TestCase):
    """deck_control.set_autostart on Linux: the XDG autostart entry, for the folder Tessera runs from."""

    def test_the_entry_is_written_found_and_removed(self):
        import deck_control
        with tempfile.TemporaryDirectory() as directory:
            root, config = Path(directory, 'tessera'), Path(directory, 'config')
            python = root / 'host/.venv/bin/python'
            python.parent.mkdir(parents=True)
            python.write_text('')
            with patch.object(deck_control, 'ROOT', root):
                self.assertFalse(deck_control.autostart_enabled(str(config)))
                path = deck_control.set_autostart(True, str(config))
                self.assertEqual(path, config / 'autostart/tessera.desktop')
                self.assertIn(str(root / 'host/tessera_tray.py'), path.read_text(encoding='utf-8'))
                self.assertTrue(deck_control.autostart_enabled(str(config)))
                deck_control.set_autostart(False, str(config))
                self.assertFalse(deck_control.autostart_enabled(str(config)))

    def test_without_the_virtual_environment_it_says_what_to_run(self):
        import deck_control
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(deck_control, 'ROOT', Path(directory, 'tessera')), \
                    self.assertRaisesRegex(OSError, 'Tessera.sh'):
                deck_control.set_autostart(True, str(Path(directory, 'config')))
            self.assertFalse(Path(directory, 'config/autostart/tessera.desktop').exists())


class EntryTests(unittest.TestCase):
    def test_a_desktop_entry_quotes_its_command(self):
        text = desktop_entries.entry(['/home/a b/python', 'x"y.py'], Path('/work dir'))
        self.assertIn('Exec="/home/a b/python" "x\\"y.py"', text)
        self.assertIn('Path=/work dir', text)

    def test_the_paths_follow_the_xdg_directories(self):
        self.assertEqual(desktop_entries.autostart_path('/cfg'), Path('/cfg/autostart/tessera.desktop'))
        self.assertEqual(desktop_entries.launcher_path('/data'), Path('/data/applications/tessera.desktop'))
        self.assertEqual(desktop_entries.config_home({'XDG_CONFIG_HOME': '/c'}), Path('/c'))


if __name__ == '__main__':
    unittest.main()


class ScriptTests(unittest.TestCase):
    def test_each_script_type_gets_its_interpreter(self):
        from platform_linux import scripts
        which = lambda name: f'/usr/bin/{name}' if name in ('python3', 'bash', 'node', 'pwsh') else None
        self.assertEqual(scripts.command('/x/a.py', which), ['/usr/bin/python3', '/x/a.py'])
        self.assertEqual(scripts.command('/x/a.PYW', which), ['/usr/bin/python3', '/x/a.PYW'])
        self.assertEqual(scripts.command('/x/a.sh', which), ['/usr/bin/bash', '/x/a.sh'])
        self.assertEqual(scripts.command('/x/a.js', which), ['/usr/bin/node', '/x/a.js'])
        self.assertEqual(scripts.command('/x/a.ps1', which), ['/usr/bin/pwsh', '-NoProfile', '-NonInteractive', '-File', '/x/a.ps1'])

    def test_a_missing_interpreter_and_a_windows_only_type_say_so(self):
        from platform_linux import scripts
        nothing = lambda name: None
        with self.assertRaisesRegex(ValueError, 'Node.js'):
            scripts.command('/x/a.js', nothing)
        with self.assertRaisesRegex(ValueError, 'pwsh'):
            scripts.command('/x/a.ps1', nothing)
        for name in ('/x/a.bat', '/x/a.cmd', '/x/a.ahk', '/x/noext'):
            with self.assertRaisesRegex(ValueError, 'not supported on Linux'):
                scripts.command(name, nothing)
        self.assertEqual(scripts.command('/x/a.py', nothing)[0], sys.executable)  # the host's own Python as the last resort
        with self.assertRaisesRegex(ValueError, 'shell'):
            scripts.command('/x/a.sh', nothing)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux only')
    def test_the_host_uses_it_and_accepts_sh_scripts(self):
        import desktop
        import script_files
        self.assertIn('.sh', script_files.SCRIPT_SUFFIXES)
        command = desktop.script_command('/x/a.sh')
        self.assertEqual((os.path.basename(command[0]) in ('bash', 'sh'), command[1]), (True, '/x/a.sh'))


class OpenPathTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux only')
    def test_a_path_is_opened_with_xdg_open(self):
        import desktop
        with patch('shutil.which', side_effect=lambda name: '/usr/bin/' + name), patch('subprocess.Popen') as popen:
            desktop.open_path(Path('/home/a/host.log'))
        self.assertEqual(popen.call_args.args[0], ['xdg-open', '/home/a/host.log'])
