"""Connect Claude Code to the panel: install or remove Tessera's hooks in ~/.claude/settings.json.

Two independent parts, both explicit and reversible:
  events      the state hooks (working, waiting for you, idle) that feed the agents screen
  permission  the PermissionRequest hook that lets Allow and Deny on the panel answer Claude's questions

Only entries whose command runs deckctl.py are ever added or removed. Everything else in the file is left as it is,
a backup is written before every change, and a file Tessera cannot read as JSON is never touched.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import time
from pathlib import Path

import adapters
import permission

MARKER = 'deckctl.py'
EVENTS = adapters.CLAUDE_EVENTS


def settings_path(home: Path | None = None) -> Path:
    return Path(home or Path.home()) / '.claude' / 'settings.json'


def _runs(hook, deckctl: Path | None = None) -> bool:
    """A Tessera hook; with `deckctl`, only one that runs that copy's deckctl.py (the path is quoted in the command)."""
    command = str(hook.get('command', '')) if isinstance(hook, dict) else ''
    return MARKER in command and (deckctl is None or f'"{deckctl}"' in command)


def _ours(entry, deckctl: Path | None = None) -> bool:
    return isinstance(entry, dict) and any(_runs(hook, deckctl) for hook in entry.get('hooks', []))


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('Claude settings cannot be read as JSON; nothing was changed.') from exc
    if not isinstance(document, dict) or not isinstance(document.get('hooks', {}), dict):
        raise ValueError('Claude settings have an unexpected shape; nothing was changed.')
    return document


def state(home: Path | None = None, deckctl: Path | None = None) -> dict:
    """{'events': bool, 'permission': bool}: which parts are installed right now. With `deckctl`, hooks that run
    another folder's copy do not count: they are what a moved Tessera leaves behind and need switching on again."""
    hooks = _read(settings_path(home)).get('hooks', {})
    on = lambda event: any(_ours(entry, deckctl) for entry in hooks.get(event, []))  # noqa: E731
    return {'events': all(on(event) for event in EVENTS), 'permission': on('PermissionRequest')}


def update(events: bool, allow: bool, python: Path, deckctl: Path, home: Path | None = None,
           only_this: bool = False) -> dict:
    """Make the file match the wish; returns the new state. A backup of the old file is kept next to it.

    Hooks of Tessera in another folder are replaced when switching on, but with `only_this` (an uninstall) they stay:
    that copy is still in use."""
    if type(events) is not bool or type(allow) is not bool:
        raise ValueError('Choose on or off for each part.')
    path = settings_path(home)
    original = _read(path)
    document = copy.deepcopy(original)
    hooks = document.setdefault('hooks', {})
    command = adapters.deckctl_command(python, deckctl)
    wanted = {event: events for event in EVENTS}
    wanted['PermissionRequest'] = allow
    for event, present in wanted.items():
        kept = []
        for entry in hooks.get(event, []):
            if _ours(entry, deckctl if only_this else None):  # a group may hold the user's own hook next to Tessera's: only Tessera's goes
                entry = dict(entry, hooks=[hook for hook in entry['hooks'] if not _runs(hook, deckctl if only_this else None)])
                if not entry['hooks']:
                    continue
            kept.append(entry)
        if present:
            if event == 'PermissionRequest':
                entry = {'matcher': '', 'hooks': [{'type': 'command', 'timeout': permission.WAIT_SECONDS + 5,
                                                   'command': command.removesuffix('adapter claude') + 'permission'}]}
            else:
                entry = adapters.claude_hooks(command)['hooks'][event][0]
            kept.append(entry)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if not hooks:
        document.pop('hooks', None)
    if document != original:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            # Two changes in one second (events, then permission) must not overwrite the first backup: that one
            # holds the user's original settings. 'xb' never replaces a file, so a taken name gets a counter.
            stamp, data = time.strftime('%Y%m%d-%H%M%S'), path.read_bytes()
            for number in range(1, 1000):
                suffix = '' if number == 1 else f'-{number}'
                kept = path.with_name(f'settings.tessera-backup-{stamp}{suffix}.json')
                try:
                    with open(kept, 'xb') as backup:
                        backup.write(data)
                    shutil.copymode(path, kept)  # the settings can hold tokens: a copy is no more readable than they are
                    break
                except FileExistsError:
                    continue
            else:
                raise OSError('No free name for a backup of the Claude settings')
        temporary = path.with_suffix('.tmp')
        temporary.write_text('', encoding='utf-8')
        if path.exists():
            shutil.copymode(path, temporary)
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        os.replace(temporary, path)
    return state(home)
