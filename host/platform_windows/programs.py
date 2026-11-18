"""Find a program when the path in a profile does not exist on this PC.

Default profiles name programs by their usual install path. Installs move: another drive, the
32-bit Program Files folder, a per-user install, a newer version folder. `locate` tries, in order:
the path itself, the Windows "App Paths" registry, PATH, the same relative path under every program
root, and the same path with version segments (10.0, Office16 ...) replaced by wildcards.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
from pathlib import Path, PureWindowsPath

from script_files import BATCH_SUFFIXES, SCRIPT_SUFFIXES, SCRIPT_VARIABLE, script_text  # noqa: F401

ROOT_VARIABLES = ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432', 'LOCALAPPDATA', 'APPDATA')
VERSION_SEGMENT = re.compile(r'(?i)^(\d+(\.\d+)*|[A-Za-z]+\d+(\.\d+)*|v\d+(\.\d+)*)$')
PROGRAM_SUFFIXES = ('.exe', '.bat', '.cmd', '.com', '.lnk')


def program_roots(environment=None) -> list[Path]:
    """Folders programs are installed under on this PC, without duplicates."""
    environment = os.environ if environment is None else environment
    roots, seen = [], set()
    for name in ROOT_VARIABLES:
        value = environment.get(name)
        if not value:
            continue
        base = Path(value)
        for folder in [base] + ([base / 'Programs'] if name == 'LOCALAPPDATA' else []):
            key = str(folder).casefold()
            if key not in seen:
                seen.add(key)
                roots.append(folder)
    return roots


def _relative_tail(path: str) -> PureWindowsPath | None:
    """The part of `path` after a 'Program Files' / 'Programs' style folder."""
    parts = PureWindowsPath(path).parts
    for index, part in enumerate(parts):
        lowered = part.casefold()
        if lowered.startswith('program files') or lowered == 'programs':
            return PureWindowsPath(*parts[index + 1:]) if index + 1 < len(parts) else None
    return None


def _wildcard_versions(tail: PureWindowsPath) -> str:
    """The tail with version-looking folders replaced by `*` (the file name is kept)."""
    parts = list(tail.parts)
    last = len(parts) - 1
    return str(PureWindowsPath(*[('*' if index < last and VERSION_SEGMENT.match(part) else part)
                                 for index, part in enumerate(parts)]))


def _natural_key(path: str) -> list:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', path)]


def _app_paths(name: str) -> str | None:
    try:
        import winreg
    except ImportError:
        return None
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, rf'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}', 0,
                                    winreg.KEY_READ | view) as key:
                    value = winreg.QueryValueEx(key, None)[0]
            except OSError:
                continue
            value = os.path.expandvars(str(value).strip('"'))
            if os.path.isfile(value):
                return value
    return None


def locate(target: str, environment=None, registry=_app_paths) -> str | None:
    """Return an existing file for `target`, or None. Targets that are not file paths are not handled."""
    if not target or '://' in target or not target.lower().endswith(PROGRAM_SUFFIXES):
        return None  # a web link such as https://host/setup.exe is not a local file name
    expanded = os.path.expandvars(target)
    if os.path.isfile(expanded):
        return expanded
    name = PureWindowsPath(expanded).name
    found = registry(name) or shutil.which(name)
    if found:
        return found
    roots = program_roots(environment)
    tail = _relative_tail(expanded)
    if tail is None:
        return None
    for root in roots:
        candidate = root / str(tail)
        if candidate.is_file():
            return str(candidate)
    pattern = _wildcard_versions(tail)
    if '*' in pattern:
        for root in roots:
            matches = sorted(glob.glob(str(root / pattern)), key=_natural_key, reverse=True)  # newest-looking version first
            if matches:
                return matches[0]
    return None


AUTOHOTKEY_NAMES = ('AutoHotkey64.exe', 'AutoHotkey32.exe', 'AutoHotkey.exe', 'AutoHotkeyU64.exe')
COMMAND_TOKEN = re.compile(r'"([^"]*)"|(\S+)')


def _association(suffix: str) -> str | None:
    """The open command Windows has registered for a file type, such as '"AutoHotkey64.exe" "%1" %*'."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, suffix) as key:
            progid = winreg.QueryValueEx(key, None)[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf'{progid}\shell\open\command') as key:
            return str(winreg.QueryValueEx(key, None)[0])
    except (ImportError, OSError):
        return None


def _association_argv(command: str | None, script: str) -> list[str] | None:
    """The argument list of an open command with %1 replaced by the script, when its program exists."""
    if not command:
        return None
    argv = []
    for quoted, bare in COMMAND_TOKEN.findall(os.path.expandvars(command)):
        token = quoted or bare
        if token == '%*':
            continue
        argv.append(token.replace('%1', script).replace('%L', script))
    return argv if argv and os.path.isfile(argv[0]) else None


def script_command(script: str, which=shutil.which, registry=_app_paths, association=_association,
                   roots=program_roots) -> list[str] | str:
    """The command that runs a script file, chosen by its extension; ValueError names what is missing.

    An argument list, except for .bat and .cmd: that is one quoted command line string.

    Python goes through the py launcher (python on PATH if there is no launcher); .ahk uses the program Windows has
    registered for the type, then App Paths, PATH and the installer's folders (Program Files, or
    %LOCALAPPDATA%\\Programs for a per-user install, which adds neither App Paths nor PATH); PowerShell and cmd come
    with Windows. The script itself must exist.
    """
    suffix = os.path.splitext(script)[1].lower()
    if suffix not in SCRIPT_SUFFIXES:
        raise ValueError(f'Script type {suffix or "(none)"} is not supported. Use {", ".join(SCRIPT_SUFFIXES)}')
    if suffix in BATCH_SUFFIXES:
        if '%' in script:  # cmd expands %NAME% even inside quotes
            raise ValueError('The path of a .bat or .cmd file cannot contain a % sign')
        # CreateProcess starts cmd.exe for these itself. The path is a ready command line, always quoted, so cmd
        # never parses & ^ ( ) in it (a list would be quoted only when it holds a space).
        return f'"{script}"'
    if suffix == '.ps1':
        # -ExecutionPolicy Bypass applies to this one process only; the user's own setting is not changed, and a policy
        # set by an administrator (Group Policy) still wins. Without it a script saved from the web would not start.
        shell = which('powershell.exe') or which('pwsh.exe')
        if not shell:
            raise ValueError('PowerShell was not found on this PC')
        return [shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', script]
    if suffix in ('.py', '.pyw'):
        launcher = which('pyw.exe' if suffix == '.pyw' else 'py.exe')
        if launcher:
            return [launcher, '-3', script]
        fallback = which('pythonw.exe' if suffix == '.pyw' else 'python.exe')
        if not fallback:
            raise ValueError('Python was not found on this PC (the py launcher or python on PATH)')
        return [fallback, script]
    if suffix == '.js':
        node = which('node.exe') or which('node')
        if not node:
            raise ValueError('Node.js (node) was not found on this PC')
        return [node, script]
    argv = _association_argv(association('.ahk'), script)
    if argv:
        return argv
    for name in AUTOHOTKEY_NAMES:
        found = registry(name) or which(name)
        if found:
            return [found, script]
    for root in roots():
        for folder in ('AutoHotkey/v2', 'AutoHotkey'):  # v2 first: it is the version the installer sets up now
            for name in AUTOHOTKEY_NAMES:
                if (root / folder / name).is_file():
                    return [str(root / folder / name), script]
    raise ValueError('AutoHotkey was not found on this PC')


def describe(target: str) -> dict:
    """{'name', 'process'} of a program picked from the list: a file or shortcut, or a Store app; ValueError otherwise."""
    from platform_windows.shell import shortcut_target
    path = Path(target)
    store_app = target.startswith('shell:AppsFolder\\')
    if not store_app and (not path.is_file() or path.suffix.lower() not in ('.exe', '.lnk', '.cmd', '.bat')):
        raise ValueError('Choose a local program file or shortcut')
    resolved = target if store_app else shortcut_target(path)
    process = Path(resolved).name if Path(resolved).suffix.lower() == '.exe' else ''
    if store_app:
        lowered = target.casefold()
        process = ('ChatGPT.exe' if 'openai.codex_' in lowered else
                   'claude.exe' if 'claude_' in lowered else
                   'XboxPcApp.exe' if 'microsoft.gamingapp_' in lowered else '')
    return {'name': path.stem, 'process': process}
