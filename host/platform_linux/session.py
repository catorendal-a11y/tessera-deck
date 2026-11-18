"""Is the screen locked? (The Windows host asks the secure desktop; here: logind and the desktop's screensaver.)

Any source that says "locked" wins; a source that cannot be asked counts as unlocked. The answer is kept for two
seconds, because the host asks many times a second and each question starts a short command.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

TTL = 2.0
TIMEOUT = 1.0
SCREENSAVERS = ('org.cinnamon.ScreenSaver', 'org.gnome.ScreenSaver', 'org.mate.ScreenSaver', 'org.freedesktop.ScreenSaver')
_cache = (0.0, False)


def _run(args: list[str]) -> str:
    if shutil.which(args[0]) is None:
        return ''
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT, check=False).stdout
    except (subprocess.TimeoutExpired, OSError):
        return ''


def _logind(run=_run) -> bool:
    return run(['loginctl', 'show-session', os.environ.get('XDG_SESSION_ID') or 'auto', '--property=LockedHint',
                '--value']).strip() == 'yes'


def _screensavers(run=_run) -> bool:
    names = run(['gdbus', 'call', '--session', '--dest', 'org.freedesktop.DBus', '--object-path', '/org/freedesktop/DBus',
                 '--method', 'org.freedesktop.DBus.ListNames'])
    for service in SCREENSAVERS:
        if f"'{service}'" not in names:
            continue
        path = '/' + service.replace('.', '/')
        reply = run(['gdbus', 'call', '--session', '--timeout', '1', '--dest', service, '--object-path', path,
                     '--method', f'{service}.GetActive'])
        if reply.strip().startswith('(true'):
            return True
    return False


def locked(now=time.monotonic, run=_run) -> bool:
    global _cache
    at, value = _cache
    if now() - at < TTL:
        return value
    value = _logind(run) or _screensavers(run)
    _cache = (now(), value)
    return value
