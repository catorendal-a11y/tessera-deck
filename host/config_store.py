"""Configuration versioning, migrations and rotating backups for profiles.json."""
from __future__ import annotations

import copy
import json
import re
import shutil
import time
from pathlib import Path
from typing import Callable

CONFIG_VERSION = 2
BACKUP_KEEP = 30
BACKUP_INTERVAL_SECONDS = 600
BACKUP_NAME = re.compile(r'profiles-\d{8}-\d{6}(?:-\d+)?\.json')


class FutureConfig(ValueError):
    """The file was written by a newer Tessera than this one."""


def version_of(config: dict) -> int:
    version = config.get('version', 1) if isinstance(config, dict) else 1
    if type(version) is not int or version < 1:
        raise ValueError('The configuration version must be a whole number from 1')
    return version


def _v1_to_v2(config: dict) -> dict:
    # Version 2 added counters, timers, key colors, the ambient screen and long-press actions.
    # They are all optional fields, so an older file needs no structural change.
    return config


MIGRATIONS: dict[int, Callable[[dict], dict]] = {1: _v1_to_v2}


def migrate(config: dict) -> dict:
    """A copy of `config` brought up to CONFIG_VERSION; refuses files from the future."""
    version = version_of(config)
    if version > CONFIG_VERSION:
        raise FutureConfig(f'This configuration was saved by a newer Tessera (version {version}); '
                           f'this one understands up to {CONFIG_VERSION}. Update Tessera to open it.')
    result = copy.deepcopy(config)
    while version < CONFIG_VERSION:
        result = MIGRATIONS[version](result)
        version += 1
    result['version'] = CONFIG_VERSION
    return result


def backups_dir(path: Path) -> Path:
    return Path(path).with_name('backups')


def backup(path: Path, force: bool = False, keep: int = BACKUP_KEEP, interval: int = BACKUP_INTERVAL_SECONDS,
           now: Callable[[], float] = time.time) -> Path | None:
    """Copy the current file into backups/ unless a recent copy exists (or `force`); prune old copies."""
    path = Path(path)
    if not path.is_file():
        return None
    folder = backups_dir(path)
    folder.mkdir(parents=True, exist_ok=True)
    existing = sorted(folder.glob('profiles-*.json'))
    current = path.read_bytes()
    if existing and not force:
        newest = existing[-1]
        if now() - newest.stat().st_mtime < interval or newest.read_bytes() == current:
            return None
    stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(now()))
    target = folder / f'profiles-{stamp}.json'
    counter = 1
    while target.exists():
        target = folder / f'profiles-{stamp}-{counter}.json'
        counter += 1
    shutil.copyfile(path, target)
    for old in sorted(folder.glob('profiles-*.json'))[:-keep]:
        old.unlink(missing_ok=True)
    return target


def list_backups(path: Path) -> list[dict]:
    """Backups, newest first, with what is inside so the user can recognise the right one."""
    found = []
    for file in sorted(backups_dir(path).glob('profiles-*.json'), reverse=True):
        if not BACKUP_NAME.fullmatch(file.name):
            continue
        try:
            data = json.loads(file.read_text(encoding='utf-8'))
            profiles = data['profiles']
            buttons = sum(len(page) for profile in profiles.values() for page in profile['pages'].values())
            found.append({'name': file.name, 'saved': time.strftime('%Y-%m-%d %H:%M:%S',
                                                                   time.localtime(file.stat().st_mtime)),
                          'bytes': file.stat().st_size, 'profiles': len(profiles), 'buttons': buttons,
                          'version': version_of(data)})
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return found


def read_backup(path: Path, name: str) -> dict:
    """The (migrated, not yet validated) configuration stored in backup `name`."""
    if not isinstance(name, str) or not BACKUP_NAME.fullmatch(name):
        raise ValueError('Choose a backup from the list')
    file = backups_dir(path) / name
    try:
        return migrate(json.loads(file.read_text(encoding='utf-8')))
    except FileNotFoundError as exc:
        raise ValueError('That backup no longer exists') from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'That backup cannot be read: {exc}') from exc
