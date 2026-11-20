"""The windows of a GNOME Wayland session, through the Tessera extension for GNOME Shell (host/linux/gnome-extension).

GNOME shows a program no other windows, so the Shell itself answers: the extension exports org.tessera.Windows on the
session bus. Without it the questions the host asks all the time (which program is in front) get "none", and a key that
needs a window says what to install, once, instead of doing something else.
"""
from __future__ import annotations

import json
import logging
import threading

from platform_linux import BackendUnavailable
from platform_linux.portal import checked, open_connection

log = logging.getLogger(__name__)

NAME = 'org.tessera.Windows'
PATH = '/org/tessera/Windows'
MISSING = ('The Tessera extension for GNOME Shell is not installed or not enabled, so Tessera cannot find or move '
           'windows. Install it with ./Tessera.sh --gnome-extension, sign in again, then turn it on: '
           'gnome-extensions enable tessera-windows@tessera')
ABSENT = ('org.freedesktop.DBus.Error.ServiceUnknown', 'org.freedesktop.DBus.Error.NameHasNoOwner',
          'org.freedesktop.DBus.Error.NoReply')
TIMEOUT = 3.0
ASKED_AGAIN = ('Active', 'Find')  # questions; anything else changes a window, and is sent once only


class GnomeWindows:
    """find, focus and arrange windows; `call(member, signature, body)` is replaceable so the tests need no desktop."""

    def __init__(self, call=None, connect=open_connection):
        self._call_override = call
        self._connect = connect
        self._connection = None
        self._lock = threading.Lock()
        self._said = False

    def _call(self, member: str, signature: str, body: tuple) -> tuple:
        if self._call_override:
            return self._call_override(member, signature, body)
        from jeepney import DBusAddress, new_method_call
        message = new_method_call(DBusAddress(PATH, bus_name=NAME, interface=NAME), member, signature, body)
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._connection is None:
                        self._connection = self._connect()
                    return checked(self._connection.send_and_get_reply(message, timeout=TIMEOUT)).body
                except BackendUnavailable:
                    raise
                except Exception as exc:
                    if getattr(exc, 'name', '') in ABSENT:
                        raise BackendUnavailable(MISSING) from exc
                    self._connection = None  # a dropped connection: one more try with a new one
                    if member not in ASKED_AGAIN and isinstance(exc, OSError):
                        # no answer in time, or the connection went: the Shell may have carried it out all the same, and
                        # a second send would do it twice
                        raise OSError(f'The Tessera GNOME extension did not answer ({exc or type(exc).__name__}), so it '
                                      'is not known whether the window was changed. It was not tried again.') from exc
                    if attempt == 2 or member not in ASKED_AGAIN:
                        raise OSError(f'The Tessera GNOME extension did not answer: {exc}') from exc

    def _quiet(self, member: str, signature: str, body: tuple, empty):
        """A question the host asks all the time: without the extension the answer is "nothing", said once in the log."""
        try:
            return self._call(member, signature, body)
        except BackendUnavailable:
            if not self._said:
                self._said = True
                log.warning(MISSING)
            return empty

    def active_window(self):
        reply = self._quiet('Active', '', (), ('',))[0]
        if not reply:
            return None
        window = json.loads(reply)
        return {'id': window['id'], 'pid': int(window.get('pid') or 0), 'title': window.get('title', '')}

    def find_window(self, pids):
        found = self._quiet('Find', 'ai', (sorted(pids),), ('',))[0]
        return found or None

    def window_op(self, window, op):
        return bool(self._call('Operate', 'ss', (window or '', op))[0])
