"""The editor's window on Linux (the Windows counterpart is platform_windows/editor_window.py with the same functions).

The editor gets a window of its own, a GTK window with WebKitGTK, so Tessera works like a program: it has its own
entry in the task bar, and closing it closes the editor while the USB host keeps running. GTK runs in a helper
(editor_window_helper.py) under the system Python, which has PyGObject; the virtual environment needs none. Without
WebKitGTK (`webkit2gtk-4.1` on Arch, `gir1.2-webkit2-4.1` on Debian or Ubuntu) the editor opens in a browser tab.
TESSERA_EDITOR=browser always uses the browser.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import psutil

HELPER = Path(__file__).with_name('editor_window_helper.py')
NO_GTK = 3


def gtk_python() -> str | None:
    from platform_linux.x11_tray_menu import gtk_python as find
    return find()


def activate_window(pid):
    """Bring the window of a running editor to the front. The window belongs to its helper process, a child of `pid`."""
    from platform_linux import backend
    try:
        pids = {child.pid for child in psutil.Process(pid).children()
                if any(part.endswith(HELPER.name) for part in child.cmdline())}
    except psutil.Error:
        return False
    if not pids:
        return False  # an editor in a browser tab, or one still starting
    try:
        window = backend().find_window(pids)
        return bool(window) and backend().window_op(window, 'focus')
    except OSError:
        return False


def brand_taskbar_identity():
    return None  # the helper names its window "tessera-editor", which the menu entry tessera-editor.desktop matches


def open_native_window(url, geometry_of, save_geometry, min_window, root):
    """Show the editor in its own window until it is closed: True. False when that cannot be done here (the caller opens
    a browser tab). `geometry_of(screen)` and `save_geometry(dict)` remember the last size and place."""
    if os.environ.get('TESSERA_EDITOR') == 'browser':
        return False
    python = gtk_python()
    if not python:
        return False
    try:
        done = subprocess.run([python, str(HELPER), '--screen'], capture_output=True, text=True, timeout=20)
        if done.returncode != 0:
            return False  # NO_GTK: no WebKitGTK here
        width, height, x, y = geometry_of(SimpleNamespace(**json.loads(done.stdout)))
        request = {'url': url, 'width': width, 'height': height, 'x': x, 'y': y, 'min_width': min_window[0],
                   'min_height': min_window[1], 'icon': str(root / 'docs/images/logo-mark.svg')}
        done = subprocess.run([python, str(HELPER)], input=json.dumps(request), capture_output=True, text=True)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        logging.getLogger(__name__).warning('The editor window failed; using the browser', exc_info=True)
        return False
    if done.returncode != 0:
        logging.getLogger(__name__).warning('The editor window failed (%s); using the browser', done.stderr.strip()[-300:])
        return False
    try:
        save_geometry(json.loads(done.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        pass
    return True
