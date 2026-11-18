"""Wayland backend: not written yet. This is the place for it.

Wayland has no portable way for a program to send keys, find the window in front or move windows. Typical ways in:
`ydotool`/uinput or the RemoteDesktop portal for input, `wl-copy` for the clipboard, and a compositor-specific
query (GNOME Shell, KWin, Hyprland, sway) for windows. Implement `DesktopBackend` from base.py here, then nothing
else needs to change: `platform_linux.backend()` already picks this module for a Wayland session.
"""
from __future__ import annotations

from platform_linux import BackendUnavailable
from platform_linux.base import DesktopBackend

MESSAGE = ('Tessera does not support Wayland sessions yet. Log in with an X11 session, or run '
           'TESSERA_SESSION=x11 with XWayland for the programs that need it.')


class WaylandBackend(DesktopBackend):
    name = 'wayland'

    def _refuse(self, *_, **__):
        raise BackendUnavailable(MESSAGE)

    send_keys = send_text = send_mouse = set_clipboard = _refuse

    def active_window(self):
        return None

    def find_window(self, pids):
        return None

    def window_op(self, window, op):
        raise BackendUnavailable(MESSAGE)
