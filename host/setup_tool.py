"""First-run setup, dependency sync, shortcut, diagnostics and uninstall for the Windows program.

Run through Tessera.cmd (`--setup`, `--uninstall`, `--diagnostics`); it is also called on every start to keep the
virtual environment in step with host/requirements.txt without re-installing when nothing changed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
HASH_FILE = ROOT / 'host/.venv/requirements.sha256'
REQUIREMENTS = ROOT / 'host/requirements.txt'
MODULE_PROBE = 'import serial, psutil, PIL, webview, win32pdh, pystray, comtypes, esptool'
MINIMUM_PYTHON = (3, 11)
USER_DATA = ('host/profiles.json', 'host/assets', 'host/backups', 'host/state.local.json', 'host/editor.local.json',
             'host/icon-library.local.json', 'host/profiles-previous.local.json', 'host/deck-device.local.json',
             'host/profiles.backup.local.json', 'diagnostics', 'firmware', 'dist')


def requirements_hash(path: Path = REQUIREMENTS) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def needs_install(stored: str | None, current: str, imports_work: bool) -> str | None:
    """Why dependencies must be installed, or None when the environment is already in step."""
    if not imports_work:
        return 'a required package is missing'
    if stored != current:
        return 'requirements.txt changed'
    return None


def imports_work(python: str = sys.executable) -> bool:
    return subprocess.run([python, '-c', MODULE_PROBE], capture_output=True).returncode == 0


def ensure(python: str = sys.executable, probe: Callable[[str], bool] = imports_work,
           install: Callable[[list[str]], int] | None = None, hash_file: Path = HASH_FILE,
           requirements: Path = REQUIREMENTS, emit: Callable[[str], None] = print) -> bool:
    """Install host/requirements.txt when needed. Returns False (with a plain explanation) when that fails."""
    if sys.version_info < MINIMUM_PYTHON:
        emit(f'Tessera needs Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer; this is {sys.version.split()[0]}.')
        return False
    current = requirements_hash(requirements)
    stored = hash_file.read_text(encoding='utf-8').strip() if hash_file.is_file() else None
    reason = needs_install(stored, current, probe(python))
    if reason is None:
        return True
    emit(f'Installing the Windows host dependencies ({reason}) ...')
    run = install or (lambda command: subprocess.run(command).returncode)
    if run([python, '-m', 'pip', 'install', '-q', '--disable-pip-version-check', '-r', str(requirements)]) != 0:
        emit('The dependencies could not be installed. Check your internet connection and try again; '
             'the error above says which package failed.')
        return False
    hash_file.parent.mkdir(parents=True, exist_ok=True)
    hash_file.write_text(current + '\n', encoding='utf-8')
    return True


def desktop_shortcut_path() -> Path:
    return Path(os.path.expandvars(r'%USERPROFILE%\Desktop')) / 'Tessera.lnk'


def create_shortcut(target: Path = ROOT / 'Tessera.cmd', link: Path | None = None) -> Path:
    """A Desktop shortcut with the Tessera icon that starts the program minimised."""
    link = link or desktop_shortcut_path()
    script = ('$s=(New-Object -ComObject WScript.Shell).CreateShortcut($args[0]);$s.TargetPath=$args[1];'
              '$s.WorkingDirectory=$args[2];$s.IconLocation=$args[3];$s.WindowStyle=7;$s.Save()')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script, str(link),
                             str(target), str(target.parent), str(target.parent / 'host/tessera.ico')],
                            capture_output=True, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise OSError(result.stderr.strip() or 'The shortcut could not be created')
    return link


def uninstall(purge: bool = False, confirm: Callable[[str], str] = input, emit: Callable[[str], None] = print,
              root: Path = ROOT, link: Path | None = None,
              autostart: Callable[[bool], object] | None = None) -> list[str]:
    """Remove what Tessera put outside its folder (autostart entry, Desktop shortcut). User data stays unless `purge`."""
    removed = []
    if autostart is None:
        sys.path.insert(0, str(root / 'host'))
        from deck_control import set_autostart as autostart
    try:
        autostart(False)
        removed.append('start with Windows')
    except OSError as exc:
        emit(f'Could not remove the autostart entry: {exc}')
    shortcut = link or desktop_shortcut_path()
    if shortcut.exists():
        shortcut.unlink()
        removed.append('Desktop shortcut')
    if purge:
        answer = confirm('This permanently deletes your profiles, icons, backups, counters and downloads. '
                         'Type YES to continue: ').strip()
        if answer != 'YES':
            emit('Nothing was deleted.')
            return removed
        for relative in USER_DATA:
            target = root / relative
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
        removed.append('your data')
    else:
        emit('Your profiles, icons and backups were kept. Run again with --purge to delete them too.')
    emit('Removed: ' + (', '.join(removed) or 'nothing'))
    return removed


def diagnostics() -> Path:
    sys.path.insert(0, str(ROOT / 'host'))
    import diagnostics as bundle
    from deck_control import Controller
    from tesserad import Daemon
    config = Daemon.load_profiles(ROOT / 'host/profiles.json')
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    return bundle.build(ROOT / 'diagnostics', config, Controller().status(), version, ROOT / 'host/deck.local.log')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('ensure', help='install dependencies when requirements.txt changed')
    commands.add_parser('setup', help='first-run setup: dependencies and a Desktop shortcut')
    remove = commands.add_parser('uninstall', help='remove the autostart entry and the Desktop shortcut')
    remove.add_argument('--purge', action='store_true', help='also delete profiles, icons, backups and downloads')
    commands.add_parser('diagnostics', help='write a support bundle without button contents')
    args = parser.parse_args(argv)
    if args.command == 'ensure':
        return 0 if ensure() else 1
    if args.command == 'setup':
        if not ensure():
            return 1
        print(f'Desktop shortcut: {create_shortcut()}')
        print('Setup is done. Start Tessera from the shortcut or with Tessera.cmd.')
        return 0
    if args.command == 'uninstall':
        uninstall(args.purge)
        return 0
    print(f'Wrote {diagnostics()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
