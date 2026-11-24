"""First-run setup, dependency sync, shortcut, diagnostics and uninstall for the program.

Run through Tessera.cmd (Windows) or Tessera.sh (Linux) with `--setup`, `--uninstall` or `--diagnostics`; it is also called on every start to keep the
virtual environment in step with host/requirements.txt (or its hashed lock file, host/requirements.lock, when
there is one) without re-installing when nothing changed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import sysconfig
import time
from pathlib import Path
from typing import Callable

from platform_support import IS_LINUX, IS_WINDOWS, load

ROOT = Path(__file__).resolve().parents[1]
HASH_FILE = ROOT / 'host/.venv/requirements.sha256'
REQUIREMENTS = ROOT / 'host/requirements.txt'
LOCK = ROOT / 'host/requirements.lock'
MODULE_PROBE = load('labels').MODULE_PROBE
MINIMUM_PYTHON = (3, 11)
# Glob patterns. host/*.local.* is every state, log, lock and copy file the host writes (profiles-*.local.json are the
# previous and the unreadable copies); profiles.json.*.tmp is a save cut short.
USER_DATA = ('host/profiles.json', 'host/assets', 'host/backups', 'host/*.local.*', 'host/profiles.json.*.tmp',
             'diagnostics', 'firmware', 'dist')


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


def venv_made_by_other_python() -> bool:
    """True when this venv was made by another major.minor Python than the one running now (pyvenv.cfg `version`)."""
    try:
        for line in (Path(sys.prefix) / 'pyvenv.cfg').read_text(encoding='utf-8').splitlines():
            key, _, value = line.partition('=')
            if key.strip() == 'version':
                return tuple(int(part) for part in value.strip().split('.')[:2]) != sys.version_info[:2]
    except (OSError, ValueError):
        pass
    return False


def install_command(python: str, requirements: Path) -> tuple[list[str], Path]:
    """The pip command and the file it installs: the lock file with its hashes when it sits next to requirements."""
    lock = requirements.with_suffix('.lock')
    base = [python, '-m', 'pip', 'install', '-q', '--disable-pip-version-check']
    if lock.is_file():  # every download must match a pinned hash, so a tampered package is refused
        return base + ['--require-hashes', '-r', str(lock)], lock
    return base + ['-r', str(requirements)], requirements


def ensure(python: str = sys.executable, probe: Callable[[str], bool] = imports_work,
           install: Callable[[list[str]], int] | None = None, hash_file: Path = HASH_FILE,
           requirements: Path = REQUIREMENTS, emit: Callable[[str], None] = print) -> bool:
    """Install the host dependencies when needed. Returns False (with a plain explanation) when that fails."""
    if sys.version_info < MINIMUM_PYTHON:
        emit(f'Tessera needs Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer; this is {sys.version.split()[0]}.'
             ' Install a newer Python, delete the folder host/.venv and start Tessera again.')
        return False
    command, source = install_command(python, requirements)
    current = requirements_hash(source)
    stored = hash_file.read_text(encoding='utf-8').strip() if hash_file.is_file() else None
    reason = needs_install(stored, current, probe(python))
    if reason is None:
        return True
    if venv_made_by_other_python():
        # the venv keeps the old minor version's folder, so the new Python finds nothing in it and pip is gone too
        emit('Python changed since host/.venv was made. Delete the folder host/.venv and start Tessera again.')
        return False
    platform = sysconfig.get_platform()
    if IS_WINDOWS and platform != 'win-amd64':
        # pyca/cryptography and psutil publish no wheels for 32-bit, arm64 or MSYS2 (mingw_*) Python on Windows, and
        # building them needs a compiler. MSYS2's UCRT64 Python is x64 already, so its message names python.org.
        need = 'the x64 Python from python.org, not MSYS2' if platform.startswith('mingw') else '64-bit (x64) Python on Windows'
        emit(f'Tessera needs {need}; this one is {platform}. '
             'Install x64 Python, delete the folder host\\.venv and start Tessera again.')
        return False
    emit(f'Installing the host dependencies ({reason}) ...')
    run = install or (lambda command: subprocess.run(command).returncode)
    if run(command) != 0:
        emit('The dependencies could not be installed. Check your internet connection and try again; '
             'the error above says which package failed.')
        return False
    hash_file.parent.mkdir(parents=True, exist_ok=True)
    hash_file.write_text(current + '\n', encoding='utf-8')
    return True


def desktop_shortcut_path() -> Path:
    return load('shortcuts').desktop_shortcut_path()


def create_shortcut(target: Path = ROOT / 'Tessera.cmd', link: Path | None = None) -> Path:
    """A shortcut with the Tessera icon: a Desktop .lnk on Windows, an application menu entry on Linux."""
    return load('shortcuts').create_shortcut(target, link or desktop_shortcut_path())


def forget_claude_hooks(home: Path | None = None, emit: Callable[[str], None] = print) -> bool:
    """Take Tessera's hooks out of Claude Code's settings: left in, every Claude Code event would go on starting
    deckctl from a folder that may be gone. True when something was removed."""
    import claude_setup
    from venv_paths import venv_python
    try:
        if not any(claude_setup.state(home).values()):
            return False
        claude_setup.update(False, False, venv_python(ROOT), ROOT / 'host/deckctl.py', home)
    except (OSError, ValueError) as exc:
        emit(f"Could not remove Tessera's hooks from Claude Code: {exc}")
        return False
    emit("Removed Tessera's hooks from Claude Code (a backup of its settings is next to them).")
    return True


def uninstall(purge: bool = False, confirm: Callable[[str], str] = input, emit: Callable[[str], None] = print,
              root: Path = ROOT, link: Path | None = None,
              autostart: Callable[[bool], object] | None = None) -> list[str]:
    """Remove what Tessera put outside its folder (autostart entry, Desktop shortcut). User data stays unless `purge`.

    Raises OSError after the report when a purge could not delete everything.
    """
    removed, failed = [], []
    own_autostart = autostart is None
    if own_autostart:
        sys.path.insert(0, str(root / 'host'))
        from deck_control import set_autostart as autostart
    try:
        had_entry = True  # a stand-in has no entry to look at
        if own_autostart:
            from deck_control import startup_script_path
            had_entry = startup_script_path().exists()
        autostart(False)
        if had_entry:
            removed.append('start with ' + load('labels').AUTOSTART_NAME)
    except OSError as exc:
        emit(f'Could not remove the autostart entry: {exc}')
    shortcuts = [path for path in load('shortcuts').shortcut_files(link or desktop_shortcut_path()) if path.exists()]
    for path in shortcuts:
        path.unlink()
    if shortcuts:
        removed.append(load('labels').SHORTCUT_NAME)
    if purge:
        answer = confirm('This permanently deletes your profiles, icons, backups, counters and downloads. '
                         'Type YES to continue: ').strip()
        if answer == 'YES':
            for pattern in USER_DATA:
                for target in sorted(root.glob(pattern)):
                    try:
                        if target.is_dir():
                            shutil.rmtree(target)
                        else:
                            target.unlink()
                    except OSError as exc:
                        failed.append(f'{target.relative_to(root)} ({exc.strerror or exc})')
            if failed:
                emit('Could not delete ' + ', '.join(failed) + '. Close Tessera (the tray icon, the host and the '
                     'editor) and run the uninstall again.')
            else:
                removed.append('your data')
        else:
            emit('Your profiles, icons and backups were kept.')
    else:
        emit('Your profiles, icons and backups were kept. Run again with --purge to delete them too.')
    emit('Removed: ' + (', '.join(removed) or 'nothing'))
    if failed:
        raise OSError('The uninstall is not complete')
    return removed


RESTART_SCRIPTS = ('tessera_tray.py', 'tesserad.py', 'tessera_app.py')


def running_programs(processes, root: Path, own: int) -> list:
    """The tray, the host and the editor that run from `root`: what stops before Tessera starts again. A copy of
    Tessera in another folder is left alone, so a path is read from the folder its process runs in."""
    wanted = {os.path.normcase(str((Path(root) / 'host' / name).resolve())) for name in RESTART_SCRIPTS}
    found = []
    for process in processes:
        try:
            if process.pid == own:
                continue
            scripts = [argument for argument in process.cmdline()[1:3] if argument.endswith('.py')]
            if any(os.path.normcase(str((Path(process.cwd()) / script).resolve())) in wanted for script in scripts):
                found.append(process)
        except Exception:  # a process that ended meanwhile, or one this account may not look at
            continue
    return found


def restart_command(root: Path) -> list[str]:
    """The start file, which also installs what a new version needs before it starts the tray and the editor."""
    launcher = str(Path(root) / load('labels').LAUNCHER)
    return [launcher, '--app'] if IS_LINUX else ['cmd', '/c', launcher]  # Tessera.sh alone starts only the tray


def restart(root: Path = ROOT, wait: Callable[[float], None] = time.sleep) -> None:
    """Stop the tray, the host and the editor of this folder and start Tessera again (after an update)."""
    import psutil
    from process_flags import DETACHED, NO_WINDOW
    wait(1.5)  # the editor first answers the page that asked for the update
    for process in running_programs(psutil.process_iter(), root, os.getpid()):
        try:
            process.terminate()
        except psutil.Error:
            pass
    wait(1.0)
    subprocess.Popen(restart_command(root), cwd=str(root), creationflags=NO_WINDOW | DETACHED, start_new_session=os.name != 'nt',
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def diagnostics() -> Path:
    sys.path.insert(0, str(ROOT / 'host'))
    import diagnostics as bundle
    from deck_control import Controller
    from tesserad import Daemon
    try:
        config = Daemon.load_profiles(ROOT / 'host/profiles.json')
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        config = None  # a broken profile file is when the bundle is needed most
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    return bundle.build(ROOT / 'diagnostics', config, Controller().status(), version, ROOT / 'host/deck.local.log')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('ensure', help='install dependencies when requirements.txt changed')
    commands.add_parser('setup', help='first-run setup: dependencies and a Desktop shortcut')
    commands.add_parser('restart', help='stop the tray, the host and the editor and start Tessera again')
    remove = commands.add_parser('uninstall', help='remove the autostart entry and the Desktop shortcut')
    remove.add_argument('--purge', action='store_true', help='also delete profiles, icons, backups and downloads')
    commands.add_parser('diagnostics', help='write a support bundle without button contents')
    args = parser.parse_args(argv)
    if args.command == 'ensure':
        return 0 if ensure() else 1
    if args.command == 'setup':
        if not ensure():
            return 1
        print(f'Shortcut: {create_shortcut()}')
        print('Setup is done. Start Tessera from the shortcut or with ' + (load('labels').LAUNCHER + '.'))
        return 0
    if args.command == 'restart':
        restart()
        return 0
    if args.command == 'uninstall':
        try:
            uninstall(args.purge)
            forget_claude_hooks()
        except OSError as exc:
            print(exc)
            return 1
        return 0
    print(f'Wrote {diagnostics()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
