"""Linux support for the host, split by what depends on the desktop session.

The input and window code depends on the display server, so it sits behind `DesktopBackend` and one module per
session type (`x11.py` today; `wayland.py` is the place for a Wayland one). Audio, media, secrets and the
autostart entry do not depend on the session and have one module each.

`desktop.py` uses `backend()` on Linux; the Windows code is in `platform_windows`.
"""
from __future__ import annotations

import os


class BackendUnavailable(OSError):
    """The desktop backend cannot do this here (a missing tool, or a session type that is not supported yet)."""


def session_type(environ=None) -> str:
    """'x11', 'wayland' or '' (unknown). TESSERA_SESSION overrides what the session says."""
    environ = os.environ if environ is None else environ
    value = (environ.get('TESSERA_SESSION') or environ.get('XDG_SESSION_TYPE') or '').strip().lower()
    if value in ('x11', 'wayland'):
        return value
    if environ.get('WAYLAND_DISPLAY'):
        return 'wayland'
    return 'x11' if environ.get('DISPLAY') else ''


_backend = None


def backend(environ=None):
    """The desktop backend of this session (made once)."""
    global _backend
    if _backend is None or environ is not None:
        kind = session_type(environ)
        if kind == 'x11':
            from platform_linux.x11 import X11Backend
            made = X11Backend()
        elif kind == 'wayland':
            from platform_linux.wayland import session_backend
            made = session_backend()
        else:
            from platform_linux.base import NoDesktopBackend
            made = NoDesktopBackend()
        if environ is not None:
            return made
        _backend = made
    return _backend
