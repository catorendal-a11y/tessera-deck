"""A support bundle the user can attach to a bug report: versions, status, counts and a cleaned log tail.

It never contains profile contents (no commands, URLs, labels or paths from buttons), only numbers about them.
User names, tokens and passwords are removed from the log before it is written.
"""
from __future__ import annotations

import json
import platform
import re
import sys
import time
import zipfile
from pathlib import Path

LOG_LINES = 400
MAX_LOG_BYTES = 256 * 1024
USER_PATH = re.compile(r'(?i)([A-Z]:[\\/]+Users[\\/]+)[^\\/"\r\n]+')  # a user name may contain spaces
BEARER = re.compile(r'(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+')
SECRET = re.compile(r'(?i)(token|secret|password|passwd|authorization|api[_-]?key|bearer)(["\']?\s*[:=]?\s*["\']?)([^\s"\',;]+)')
PACKAGES = ('pyserial', 'psutil', 'Pillow', 'pywebview', 'pywin32', 'pystray', 'pycaw', 'esptool', 'textual')


def clean(text: str) -> str:
    """Remove the user's name from paths and anything that looks like a credential."""
    text = USER_PATH.sub(r'\1<user>', BEARER.sub(r'\1 <hidden>', text))
    return SECRET.sub(lambda match: f'{match.group(1)}{match.group(2)}<hidden>', text)


def _versions() -> dict:
    from importlib import metadata
    found = {}
    for name in PACKAGES:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = None
    return found


def _counts(config: dict) -> dict:
    profiles = config.get('profiles', {})
    buttons = [button for profile in profiles.values()
               for page in list(profile.get('pages', {}).values()) + [profile.get('pinned', [])] for button in page]
    kinds: dict[str, int] = {}
    for button in buttons:
        for holder in [button, *button.get('states', [])]:
            for action in holder.get('actions', []) + holder.get('hold_actions', []):
                kind = action.get('type', '?')
                kinds[kind] = kinds.get(kind, 0) + 1
    return {'profiles': len(profiles), 'pages': sum(len(p.get('pages', {})) for p in profiles.values()),
            'buttons': len(buttons), 'triggers': len(config.get('triggers', [])), 'action_types': kinds,
            'ambient_enabled': bool(config.get('ambient', {}).get('enabled')), 'version': config.get('version')}


def log_tail(path: Path, lines: int = 200) -> str:
    """The last `lines` lines of the host log with user names and credentials removed (for the live log view)."""
    return _tail(path, max(1, min(lines, LOG_LINES)))


def _tail(path: Path, count: int = LOG_LINES) -> str:
    try:
        with open(path, 'rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - MAX_LOG_BYTES))
            lines = stream.read().decode('utf-8', 'replace').splitlines()[-count:]
    except OSError:
        return '(no log found)'
    return clean('\n'.join(lines))


def build(folder: Path, config: dict, status: dict, version: str, log_path: Path, now=time.time) -> Path:
    """Write the bundle into `folder` and return its path."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    device = status.get('device', {})
    report = {'tessera': version, 'python': sys.version.split()[0], 'platform': platform.platform(),
              'packages': _versions(), 'configuration': _counts(config),
              'host': {'running': bool(status.get('running')), 'connection': status.get('connection'),
                       'device': {key: device.get(key) for key in ('connected', 'firmware', 'protocol', 'profile',
                                                                   'page', 'buttons', 'error')},
                       'queue': status.get('queue')},
              'created': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now()))}
    target = folder / f'tessera-diagnostics-{time.strftime("%Y%m%d-%H%M%S", time.localtime(now()))}.zip'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('report.json', clean(json.dumps(report, indent=2, default=str)) + '\n')
        archive.writestr('host.log', _tail(Path(log_path)) + '\n')
    for old in sorted(folder.glob('tessera-diagnostics-*.zip'))[:-10]:
        old.unlink(missing_ok=True)
    return target
