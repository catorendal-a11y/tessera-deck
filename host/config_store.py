"""Configuration versioning, migrations and rotating backups for profiles.json."""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable

CONFIG_VERSION = 2
BACKUP_KEEP = 30
BACKUP_INTERVAL_SECONDS = 600
BACKUP_NAME = re.compile(r'profiles-\d{8}-\d{6}(?:-\d+)?\.json')


class FutureConfig(ValueError):
    """The file was written by a newer Tessera than this one."""


def write_atomic(path: Path, data: bytes) -> None:
    """Replace `path` with `data` in one step: readers see the old file or the new one, never a partial one.

    The temporary name is unique, so two processes saving at once (editor, terminal editor, tray) cannot truncate
    each other's file, and it is flushed to disk first, so a power cut cannot leave an empty file behind.
    """
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


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
    if not isinstance(config, dict):
        raise ValueError('The configuration must be a JSON object')
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


def _backup_files(folder: Path) -> list[Path]:
    """Tessera's own backups, oldest first. Name order would put 'x-1.json' before 'x.json' and '-10' before '-2',
    and would count a 'profiles-old.json' the user dropped there, so the time each was written decides."""
    files = []
    for file in Path(folder).glob('profiles-*.json'):
        if BACKUP_NAME.fullmatch(file.name):
            try:
                files.append((file.stat().st_mtime, file.name, file))
            except OSError:
                continue
    return [file for _, _, file in sorted(files)]


def check(data: bytes) -> dict:
    """The migrated, validated configuration in `data`; ValueError when the host could not use it."""
    from config_check import validate_config  # config_check imports this module
    try:
        return validate_config(migrate(json.loads(data.decode('utf-8'))))
    except (UnicodeDecodeError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError(f'The configuration cannot be read: {exc}') from exc


def backup(path: Path, force: bool = False, keep: int = BACKUP_KEEP, interval: int = BACKUP_INTERVAL_SECONDS,
           now: Callable[[], float] = time.time) -> Path | None:
    """Copy the current file into backups/ unless a recent copy exists (or `force`); prune old copies.

    A file the host cannot use is never copied: it would count as a backup and push a good one out."""
    path = Path(path)
    if not path.is_file():
        return None
    current = path.read_bytes()
    try:
        check(current)
    except ValueError:
        return None
    folder = backups_dir(path)
    folder.mkdir(parents=True, exist_ok=True)
    existing = _backup_files(folder)
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
    moment = now()
    os.utime(target, (moment, moment))  # the order of backups is this time, so it matches the name's stamp
    for old in _backup_files(folder)[:-keep]:
        if old != target:  # never the copy just made, even if the clock went back
            old.unlink(missing_ok=True)
    return target


def list_backups(path: Path) -> list[dict]:
    """Backups, newest first, with what is inside so the user can recognise the right one."""
    found = []
    for file in reversed(_backup_files(backups_dir(path))):
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


def recover(path: Path) -> str | None:
    """On start: replace an unreadable or invalid `path` with the newest backup that passes the check.

    The broken file is kept next to it as profiles-unreadable.local.json. A file from a newer Tessera is left
    alone (it is valid, just not for this version). Returns the name of the backup restored, or None."""
    path = Path(path)
    try:
        check(path.read_bytes())
        return None
    except FutureConfig:
        return None
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        pass
    for file in reversed(_backup_files(backups_dir(path))):
        try:
            data = file.read_bytes()
            check(data)
        except (OSError, ValueError):
            continue
        shutil.copyfile(path, path.with_name(path.stem + '-unreadable.local.json'))
        write_atomic(path, data)
        return file.name
    return None
