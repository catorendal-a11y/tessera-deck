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
    if not target or not target.lower().endswith(PROGRAM_SUFFIXES):
        return None
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
