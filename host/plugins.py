"""Integrations as separate processes: manifests, scoped tokens, an event log and crash-safe lifecycle.

A plugin is a folder `plugins/<id>/` with a `plugin.json` manifest and a program. Tessera starts it with its
own API token that only allows what the manifest asks for (and, for variables, only names starting with
`<id>.`), so one integration cannot overwrite another's values or press keys it was not given. The plugin
reads key presses and `plugin` action commands from `GET /v1/events` and updates keys through `vars`, `state`
and `feedback`. Plugins run with the user's own rights: there is no operating-system sandbox, so only install
plugins you trust. See docs/PLUGINS.md.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

API_VERSION = 1
PLUGIN_ID = re.compile(r'[a-z][a-z0-9-]{1,31}')
SETTING_TYPES = ('text', 'number', 'checkbox')
# Which control-API routes each permission opens. 'events' and 'read' open the GET routes.
PERMISSIONS = {'vars': ('var', 'vars'), 'press': ('press',), 'feedback': ('feedback',), 'state': ('state',),
               'events': (), 'read': ()}
MAX_SETTINGS_BYTES = 4096
MAX_EVENTS = 200
MAX_WAIT_SECONDS = 25
BACKOFF_SECONDS = (1, 2, 4, 8, 16, 32, 60)
MAX_QUICK_CRASHES = 5
STABLE_SECONDS = 60
ENV_KEEP = ('PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA',
            'PROGRAMDATA', 'HOMEDRIVE', 'HOMEPATH')


class ManifestError(ValueError):
    """A plugin folder whose manifest cannot be trusted or understood."""


@dataclass(frozen=True)
class Manifest:
    id: str
    name: str
    version: str
    command: tuple[str, ...]
    permissions: frozenset[str]
    settings: dict
    path: Path

    def routes(self) -> frozenset[str]:
        return frozenset(route for permission in self.permissions for route in PERMISSIONS[permission])


def load_manifest(folder: Path) -> Manifest:
    folder = Path(folder)
    try:
        data = json.loads((folder / 'plugin.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ManifestError(f'{folder.name}: plugin.json cannot be read: {exc}') from exc
    if not isinstance(data, dict) or data.get('api') != API_VERSION:
        wanted = data.get('api') if isinstance(data, dict) else '?'
        raise ManifestError(f'{folder.name}: this plugin needs plugin API {wanted}, Tessera speaks {API_VERSION}')
    plugin_id = data.get('id')
    if not isinstance(plugin_id, str) or not PLUGIN_ID.fullmatch(plugin_id) or plugin_id != folder.name:
        raise ManifestError(f'{folder.name}: id must be 2-32 lowercase letters, digits or dashes and match the folder name')
    for key in ('name', 'version'):
        if not isinstance(data.get(key), str) or not 1 <= len(data[key]) <= 60:
            raise ManifestError(f'{plugin_id}: {key} must be text of 1-60 characters')
    command = data.get('command')
    if (not isinstance(command, list) or not 1 <= len(command) <= 12
            or any(not isinstance(part, str) or not part or len(part) > 200 for part in command)):
        raise ManifestError(f'{plugin_id}: command must be a list of 1-12 words')
    permissions = data.get('permissions', [])
    if (not isinstance(permissions, list) or any(p not in PERMISSIONS for p in permissions)
            or len(set(permissions)) != len(permissions)):
        raise ManifestError(f'{plugin_id}: permissions must be a list of {", ".join(PERMISSIONS)}')
    settings = data.get('settings', {})
    if not isinstance(settings, dict) or len(settings) > 20:
        raise ManifestError(f'{plugin_id}: settings must be an object with at most 20 entries')
    for key, spec in settings.items():
        if (not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', str(key)) or not isinstance(spec, dict)
                or spec.get('type') not in SETTING_TYPES or not isinstance(spec.get('label', ''), str)):
            raise ManifestError(f'{plugin_id}: setting {key!r} needs a type of {", ".join(SETTING_TYPES)}')
    manifest = Manifest(plugin_id, data['name'], data['version'], tuple(command), frozenset(permissions),
                        settings, folder)
    resolve_command(manifest)  # fails early for a program outside the plugin folder
    return manifest


def resolve_command(manifest: Manifest, python: str | None = None) -> list[str]:
    """argv for the plugin: 'python' means Tessera's own interpreter; anything else must live in the plugin folder."""
    first, *rest = manifest.command
    if first == 'python':
        return [python or sys.executable, *rest]
    program = (manifest.path / first).resolve()
    try:
        program.relative_to(manifest.path.resolve())
    except ValueError as exc:
        raise ManifestError(f'{manifest.id}: the program must be inside the plugin folder') from exc
    return [str(program), *rest]


def discover(root: Path) -> tuple[list[Manifest], list[str]]:
    """Every valid plugin under `root`, and a readable problem for each folder that is not."""
    found, problems = [], []
    for folder in sorted(Path(root).glob('*')):
        if not folder.is_dir() or not (folder / 'plugin.json').exists():
            continue
        try:
            found.append(load_manifest(folder))
        except ManifestError as exc:
            problems.append(str(exc))
    return found, problems


def check_plugin_config(block) -> None:
    """Validate the `plugins` block of the configuration: {id: {enabled, settings}}."""
    if not isinstance(block, dict) or len(block) > 50:
        raise ValueError('plugins must be an object with at most 50 entries')
    for plugin_id, entry in block.items():
        if not isinstance(plugin_id, str) or not PLUGIN_ID.fullmatch(plugin_id):
            raise ValueError(f'Unknown plugin id {plugin_id!r}')
        if not isinstance(entry, dict) or type(entry.get('enabled', False)) is not bool:
            raise ValueError(f'plugins.{plugin_id}.enabled must be true or false')
        settings = entry.get('settings', {})
        if not isinstance(settings, dict) or len(json.dumps(settings)) > MAX_SETTINGS_BYTES:
            raise ValueError(f'plugins.{plugin_id}.settings must be a small object')
        if any(not isinstance(value, (str, int, float, bool)) for value in settings.values()):
            raise ValueError(f'plugins.{plugin_id}.settings can only hold text, numbers and true/false')


class EventLog:
    """The recent events plugins can read: key presses, page and profile changes and `plugin` action commands."""

    def __init__(self, maxlen: int = MAX_EVENTS, clock: Callable[[], float] = time.time):
        self._events: deque[dict] = deque(maxlen=maxlen)
        self._condition = threading.Condition()
        self._last = 0
        self._clock = clock

    def add(self, kind: str, **fields) -> int:
        with self._condition:
            self._last += 1
            self._events.append(dict(fields, id=self._last, type=kind, at=round(self._clock(), 3)))
            self._condition.notify_all()
            return self._last

    @property
    def last(self) -> int:
        with self._condition:
            return self._last

    def since(self, after: int, plugin: str | None = None, wait: float = 0.0, limit: int = 100) -> list[dict]:
        """Events newer than `after`. A plugin sees general events and only the commands addressed to it."""
        deadline = time.monotonic() + max(0.0, min(wait, MAX_WAIT_SECONDS))

        def visible():
            return [event for event in self._events if event['id'] > after
                    and (event['type'] != 'command' or event.get('plugin') == plugin)][:limit]

        with self._condition:
            events = visible()
            while not events and (remaining := deadline - time.monotonic()) > 0:
                self._condition.wait(remaining)
                events = visible()
            return events


def _blank() -> dict:
    return {'crashes': 0, 'next': 0.0, 'state': 'stopped', 'error': ''}


class PluginManager:
    """Starts enabled plugins, keeps them alive with back-off and revokes their tokens when they stop."""

    def __init__(self, root: Path, log_dir: Path, api_url: Callable[[], str], grant: Callable[..., str],
                 revoke: Callable[[str], None], spawn=subprocess.Popen, clock: Callable[[], float] = time.monotonic,
                 log: Callable[[str], None] = print, python: str | None = None):
        self.root, self.log_dir = Path(root), Path(log_dir)
        self._api_url, self._grant, self._revoke = api_url, grant, revoke
        self._spawn, self._clock, self._log, self._python = spawn, clock, log, python
        self.manifests: dict[str, Manifest] = {}
        self.problems: list[str] = []
        self.running: dict[str, dict] = {}
        self.history: dict[str, dict] = {}

    # --- discovery and lifecycle ----------------------------------------------------
    def refresh(self) -> None:
        found, self.problems = discover(self.root)
        self.manifests = {manifest.id: manifest for manifest in found}

    def sync(self, config: dict | None) -> None:
        """Make the running plugins match the configuration: start enabled ones, stop the rest, restart crashed ones."""
        config = config or {}
        self.refresh()
        for plugin_id in list(self.running):
            if not config.get(plugin_id, {}).get('enabled') or plugin_id not in self.manifests:
                self.stop(plugin_id)
        for plugin_id, entry in config.items():
            manifest = self.manifests.get(plugin_id)
            if not entry.get('enabled'):
                self.history.pop(plugin_id, None)  # turning a plugin off clears a give-up
                continue
            if manifest is None:
                continue
            current = self.running.get(plugin_id)
            if current is not None:
                if current['process'].poll() is None:
                    if current['settings'] == entry.get('settings', {}):
                        continue
                    self.stop(plugin_id)  # new settings: restart with them
                else:
                    self._crashed(plugin_id, current)
            state = self.history.setdefault(plugin_id, _blank())
            if state['state'] == 'failed' or self._clock() < state['next'] or plugin_id in self.running:
                continue
            self._start(manifest, entry.get('settings', {}))

    def _start(self, manifest: Manifest, settings: dict) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        token = self._grant(manifest.id, manifest.routes(), f'{manifest.id}.', 'events' in manifest.permissions,
                            'read' in manifest.permissions)
        environment = {key: os.environ[key] for key in ENV_KEEP if key in os.environ}
        environment.update({'PYTHONUTF8': '1', 'TESSERA_API': self._api_url(), 'TESSERA_TOKEN': token,
                            'TESSERA_PLUGIN': manifest.id, 'TESSERA_SETTINGS': json.dumps(settings)})
        log = open(self.log_dir / f'{manifest.id}.log', 'ab')
        try:
            process = self._spawn(resolve_command(manifest, self._python), cwd=manifest.path, env=environment,
                                  stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, ManifestError) as exc:
            self._revoke(token)
            self._record_failure(manifest.id, f'could not start: {exc}')
            return
        finally:
            log.close()
        self.running[manifest.id] = {'process': process, 'token': token, 'started': self._clock(),
                                     'settings': settings}
        self.history.setdefault(manifest.id, _blank())['state'] = 'running'
        self._log(f'Plugin {manifest.id} started')

    def _record_failure(self, plugin_id: str, error: str) -> None:
        state = self.history.setdefault(plugin_id, _blank())
        state['crashes'] += 1
        state['error'] = error
        state['state'] = 'failed' if state['crashes'] >= MAX_QUICK_CRASHES else 'crashed'
        state['next'] = self._clock() + BACKOFF_SECONDS[min(state['crashes'] - 1, len(BACKOFF_SECONDS) - 1)]
        self._log(f'Plugin {plugin_id} {error}; ' + ('giving up until it is turned off and on again'
                                                     if state['state'] == 'failed' else 'restarting soon'))

    def _crashed(self, plugin_id: str, current: dict) -> None:
        self._revoke(current['token'])
        del self.running[plugin_id]
        ran = self._clock() - current['started']
        if ran >= STABLE_SECONDS:
            self.history.setdefault(plugin_id, _blank())['crashes'] = 0
        self._record_failure(plugin_id, f'stopped with code {current["process"].poll()} after {ran:.0f} s')

    def stop(self, plugin_id: str) -> None:
        current = self.running.pop(plugin_id, None)
        if current is None:
            return
        self._revoke(current['token'])
        process = current['process']
        if process.poll() is None:
            from action_runner import kill_tree
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                kill_tree(process)
        self.history[plugin_id] = dict(_blank(), state='stopped')
        self._log(f'Plugin {plugin_id} stopped')

    def stop_all(self) -> None:
        for plugin_id in list(self.running):
            self.stop(plugin_id)

    # --- reporting ---------------------------------------------------------------------
    def status(self, config: dict | None = None) -> list[dict]:
        config = config or {}
        report = []
        for plugin_id, manifest in sorted(self.manifests.items()):
            state = self.history.get(plugin_id, {})
            entry = config.get(plugin_id, {})
            enabled = bool(entry.get('enabled'))
            report.append({'id': plugin_id, 'name': manifest.name, 'version': manifest.version, 'enabled': enabled,
                           'state': state.get('state', 'stopped') if enabled else 'disabled',
                           'error': state.get('error', '') if enabled else '', 'crashes': state.get('crashes', 0),
                           'permissions': sorted(manifest.permissions), 'settings': manifest.settings,
                           'values': entry.get('settings', {})})
        return report
