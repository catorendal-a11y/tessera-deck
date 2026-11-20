"""Tray icon set-up on Linux (platform_windows/tray.py is the Windows counterpart)."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

log = logging.getLogger(__name__)

WATCHER = 'org.kde.StatusNotifierWatcher'
NO_TRAY = ('This desktop shows no tray icons, so Tessera has no icon. Install and enable the "AppIndicator and '
           'KStatusNotifierItem Support" extension (GNOME), then sign in again. Tessera itself keeps running.')
WATCHER_WAIT = 10.0  # seconds: at sign-in the tray may start before the desktop's StatusNotifier host
TYPELIBS = ('AyatanaAppIndicator3', 'AppIndicator3')
GI_PROBE = "import gi, sys; print(sys.version_info[0], sys.version_info[1]); print(gi.__file__)"


def watcher_present(run=subprocess.run) -> bool:
    """Is a StatusNotifier host (the thing that draws tray icons on Wayland desktops) on the session bus?"""
    try:
        done = run(['gdbus', 'call', '--session', '--dest', 'org.freedesktop.DBus', '--object-path', '/org/freedesktop/DBus',
                    '--method', 'org.freedesktop.DBus.NameHasOwner', WATCHER], capture_output=True, text=True, timeout=3,
                   check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and done.stdout.strip().startswith('(true')


def wait_for_watcher(seconds: float | None = None, sleep=time.sleep, clock=time.monotonic) -> bool:
    """watcher_present, asked again for up to `seconds`: Tessera starts with the session and can come first."""
    deadline = clock() + (WATCHER_WAIT if seconds is None else seconds)
    while True:
        if watcher_present():
            return True
        if clock() >= deadline:
            return False
        sleep(0.5)


def system_gi_folder(run=subprocess.run, version=None) -> str | None:
    """The folder that holds the system Python's `gi` package, when that Python is the same version as this one (the
    compiled part of `gi` only loads in the same version)."""
    from platform_linux.x11_tray_menu import gtk_python
    python = gtk_python()
    version = version or sys.version_info[:2]
    if not python:
        return None
    try:
        lines = run([python, '-c', GI_PROBE], capture_output=True, text=True, timeout=15, check=False).stdout.split('\n')
        major, minor = (int(part) for part in lines[0].split())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return os.path.dirname(os.path.dirname(lines[1].strip())) if (major, minor) == tuple(version) and lines[1].strip() else None


def _typelib_available() -> bool:
    try:
        import gi
        for name in TYPELIBS:
            try:
                gi.require_version(name, '0.1')
                return True
            except ValueError:
                continue
    except ImportError:
        pass
    return False


def _x11_icon(environ) -> str:
    environ['PYSTRAY_BACKEND'] = 'xorg'
    return 'xorg'


def choose_backend(environ=None) -> str:
    """Pick the tray backend pystray should use, before it is imported. Returns what was chosen, for the log and tests.

    X11: pystray's own choice (the legacy tray, with the menu of x11_tray_menu.py). Plasma on Wayland: the X11 icon,
    which Plasma shows and whose left click opens the editor (a StatusNotifier icon has no click action of its own).
    Other Wayland desktops: StatusNotifier through
    pystray's appindicator backend, which needs `gi` from the system (the virtual environment has none: it is added to
    the end of the search path, so nothing of the environment is replaced) and a desktop that shows such icons.
    Without `gi` or the library the X11 icon is named outright (it shows through XWayland): left to itself, pystray
    would try appindicator again and stop on the missing library, or pick its GTK icon, which Wayland does not show."""
    from platform_linux import session_type
    environ = os.environ if environ is None else environ
    if environ.get('PYSTRAY_BACKEND'):
        return environ['PYSTRAY_BACKEND']
    if session_type(environ) != 'wayland':
        return 'default'
    if 'KDE' in environ.get('XDG_CURRENT_DESKTOP', '').upper().split(':'):
        return _x11_icon(environ)  # Plasma shows it through xembedsniproxy, and its left click opens the editor
    if not wait_for_watcher():
        log.warning(NO_TRAY)
        from platform_linux.notify import notify
        notify(NO_TRAY, 'Tessera')
        return 'none'
    try:
        import gi  # noqa: F401
    except ImportError:
        folder = system_gi_folder()
        if folder is None:
            log.warning('The tray needs PyGObject for the system Python (python-gobject or python3-gi).')
            return _x11_icon(environ)
        sys.path.append(folder)
    if not _typelib_available():
        log.warning('The tray needs libayatana-appindicator (the package libayatana-appindicator, or gir1.2-ayatanaappindicator3-0.1 on Debian and Ubuntu).')
        return _x11_icon(environ)
    environ['PYSTRAY_BACKEND'] = 'appindicator'
    return 'appindicator'


def no_icon(base):
    """An icon class for a desktop that shows no tray icons (`choose_backend` said 'none'): nothing is drawn, and `run`
    waits until `stop`, so the tray program starts the host and keeps it running as it does behind a real icon. `base`
    is pystray's Icon without a backend."""
    import threading

    class NoIcon(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._stopped = threading.Event()

        def _run(self):
            self._mark_ready()
            self._stopped.wait()

        def _stop(self):
            self._stopped.set()

        def _show(self):
            pass

        _hide = _update_icon = _update_title = _update_menu = _remove_notification = _show

    return NoIcon


def prepare(icon, separator) -> None:
    """Notices go to the desktop's notifications (notify-send), whichever tray backend pystray picked. pystray's
    legacy X11 tray has no right-click menu of its own, so one is added; it is the backend on X11, and on a Wayland
    desktop (through XWayland) when StatusNotifier could not be used. An icon with a menu of its own (StatusNotifier
    through pystray's appindicator backend) is left alone."""
    from platform_linux.notify import notify
    from platform_linux import x11_tray_menu
    icon.notify = lambda message, title=None: notify(message, title or 'Tessera')
    x11_tray_menu.attach(icon, separator)
