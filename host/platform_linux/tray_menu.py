"""A right-click menu for pystray's X11 tray icon.

pystray's X11 backend (the legacy system tray, which is what a panel without a StatusNotifier watcher shows) has no
menu: it only runs the default action on a left click. `attach(icon)` keeps that and shows the icon's own pystray menu
on a right click.

The menu is a native GTK menu, so it follows the desktop theme and closes the way every GTK menu does (Esc, a click
elsewhere). GTK runs in a small helper process (gtk_menu_helper.py) under the system Python, which has PyGObject; the
project's own virtual environment needs none. Without a system Python that has GTK, the menu is drawn with tkinter
instead (set TESSERA_TRAY_MENU=tk to force that).

The menu is read from `icon.menu` each time it opens, so it shows the current status, the ticks and the enabled items.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

HELPER = Path(__file__).with_name('gtk_menu_helper.py')
SYSTEM_PYTHONS = ('/usr/bin/python3', '/usr/bin/python')
GTK_PROBE = 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk'
_gtk_python = []  # [path or None], filled once

POPUP_SECONDS = 30  # an unanswered menu closes by itself


def describe(menu, separator) -> list[dict]:
    """The items of a pystray Menu as plain data: text, enabled, checked, radio, submenu, action, separator."""
    rows = []
    for item in menu.items:
        if item is separator or getattr(item, '_text', None) == '- - - -':
            rows.append({'separator': True})
            continue
        sub = item.submenu
        rows.append({'text': str(item.text), 'enabled': bool(item.enabled), 'checked': item.checked, 'radio': bool(item.radio),
                     'default': bool(item.default), 'submenu': describe(sub, separator) if sub else None, 'item': item})
    return rows


def label(row: dict) -> str:
    mark = ('● ' if row['radio'] else '✓ ') if row['checked'] else ('    ' if row['checked'] is not None else '')
    return mark + row['text']


def build(tk, parent, rows, run):
    """Fill a tk.Menu from `describe` rows; `run(item)` is called when an entry is chosen."""
    for row in rows:
        if row.get('separator'):
            parent.add_separator()
        elif row['submenu'] is not None:
            child = tk.Menu(parent, tearoff=0)
            build(tk, child, row['submenu'], run)
            parent.add_cascade(label=label(row), menu=child, state='normal' if row['enabled'] else 'disabled')
        else:
            parent.add_command(label=label(row), state='normal' if row['enabled'] else 'disabled',
                               command=lambda item=row['item']: run(item))


def plain(rows: list[dict]) -> list[dict]:
    """The rows without the pystray items, as JSON for the helper."""
    return [{key: (plain(value) if key == 'submenu' and value else value) for key, value in row.items() if key != 'item'}
            for row in rows]


def pick(rows: list[dict], path: str):
    """The pystray item at a helper path such as "3" or "5.1"; None when it does not exist."""
    item = None
    for part in path.split('.'):
        try:
            row = rows[int(part)]
        except (ValueError, IndexError):
            return None
        item, rows = row.get('item'), row.get('submenu') or []
    return item


def gtk_python(run=subprocess.run) -> str | None:
    """A Python that has GTK 3 (the system one, outside the virtual environment); None when there is none."""
    if _gtk_python:
        return _gtk_python[0]
    candidates = list(SYSTEM_PYTHONS) + [shutil.which('python3') or '']
    found = None
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate) or os.path.realpath(candidate).startswith(os.path.realpath(sys.prefix)):
            continue
        try:
            if run([candidate, '-c', GTK_PROBE], capture_output=True, timeout=15).returncode == 0:
                found = candidate
                break
        except (OSError, subprocess.SubprocessError):
            continue
    _gtk_python.append(found)
    return found


class TrayMenu:
    def __init__(self, icon, separator):
        self.icon, self.separator = icon, separator
        self._open = threading.Lock()

    def show(self, x: int, y: int) -> bool:
        """Open the menu at the pointer from its own thread; False when one is already open."""
        if not self._open.acquire(blocking=False):
            return False
        threading.Thread(target=self._run, args=(x, y), name='tray-menu', daemon=True).start()
        return True

    def _run(self, x, y):
        try:
            rows = describe(self.icon.menu, self.separator)
            chosen = None if os.environ.get('TESSERA_TRAY_MENU') == 'tk' else self._gtk(rows, x, y)
            if chosen is None:
                self._tk(rows, x, y)
            elif chosen:
                item = pick(rows, chosen)
                if item is not None:
                    threading.Thread(target=item, args=(self.icon,), daemon=True).start()
        except Exception:  # no menu at all: the left click still works
            self.icon._log.error('The tray menu could not be shown', exc_info=True)
        finally:
            self._open.release()

    def _gtk(self, rows, x, y):
        """The chosen entry's path, '' when the menu was closed without a choice, None when GTK cannot be used."""
        python = gtk_python()
        if not python:
            return None
        try:
            done = subprocess.run([python, str(HELPER)], input=json.dumps({'x': x, 'y': y, 'rows': plain(rows)}),
                                  capture_output=True, text=True, timeout=POPUP_SECONDS + 15)
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode != 0:  # 3: no GTK here; anything else: the helper failed. Either way the Tk menu takes over
            return None
        return done.stdout.strip()

    def _tk(self, rows, x, y):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        menu = tk.Menu(root, tearoff=0)
        build(tk, menu, rows, lambda item: threading.Thread(target=item, args=(self.icon,), daemon=True).start())
        closing = []

        def close(*_):
            if not closing:
                closing.append(True)
                root.after(60, root.destroy)  # after the chosen entry has run its command

        menu.bind('<Unmap>', close)
        root.after(POPUP_SECONDS * 1000, close)
        root.update_idletasks()
        menu.tk_popup(x, y)
        menu.focus_force()
        root.mainloop()


def attach(icon, separator) -> bool:
    """Give an icon without menu support (pystray's X11 backend) a right-click menu. False if it already has one."""
    if getattr(icon, 'HAS_MENU', True):
        return False
    try:
        import Xlib.X
    except ImportError:
        return False
    tray = TrayMenu(icon, separator)

    def on_button_press(event):
        if event.detail == 1:
            icon()  # the default action, as pystray does
        elif event.detail == 3:
            tray.show(event.root_x, event.root_y)

    icon._message_handlers[Xlib.X.ButtonPress] = on_button_press
    icon.tray_menu = tray
    threading.Thread(target=gtk_python, daemon=True).start()  # find the GTK Python now, not at the first right click
    return True
