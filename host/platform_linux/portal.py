"""Keyboard and pointer input on Wayland through the RemoteDesktop portal (org.freedesktop.portal.RemoteDesktop).

A Wayland compositor lets no program send keys on its own. The portal is the way the desktop offers: the program asks,
the desktop shows a dialog once, and from then on the session accepts key and pointer events. The permission is kept
(`persist_mode` 2 and a restore token in `host/remote-desktop.local.json`), so the dialog comes at the first key press
ever, not at every start of the host.

One session lives as long as its D-Bus connection, so the host keeps one connection and one session, and all calls take
a lock: the press threads of the host share it. `connect` is a parameter so the tests need no desktop.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from platform_linux import BackendUnavailable

log = logging.getLogger(__name__)

BUS = 'org.freedesktop.portal.Desktop'
PATH = '/org/freedesktop/portal/desktop'
INTERFACE = 'org.freedesktop.portal.RemoteDesktop'
REQUEST = 'org.freedesktop.portal.Request'
KEYBOARD, POINTER = 1, 2
PERSIST_UNTIL_REVOKED = 2
RESPONSE_WAIT = 10.0  # seconds a portal call may take to answer
DIALOG_WAIT = 120.0  # seconds the user has to answer the permission dialog
BUTTONS = {'left': 0x110, 'right': 0x111, 'middle': 0x112}  # Linux input event codes (BTN_LEFT ...)
AXIS_VERTICAL = 0


def _record_path() -> Path:
    return Path(__file__).resolve().parents[1] / 'remote-desktop.local.json'


def open_connection():
    """A blocking connection to the session bus (jeepney, which the host already needs for MPRIS)."""
    try:
        from jeepney.io.blocking import open_dbus_connection
        return open_dbus_connection(bus='SESSION')
    except ImportError as exc:
        raise BackendUnavailable('The jeepney package is missing: run Tessera.sh --setup') from exc
    except OSError as exc:
        raise BackendUnavailable(f'The session bus is not reachable: {exc}') from exc


def checked(reply):
    """The reply, or DBusErrorResponse when it is an error message: jeepney's blocking connection hands those back as
    ordinary replies, and a failed call would go unnoticed."""
    header = getattr(reply, 'header', None)
    if header is not None:
        from jeepney import MessageType
        from jeepney.wrappers import DBusErrorResponse
        if header.message_type == MessageType.error:
            raise DBusErrorResponse(reply)
    return reply


class RemoteDesktop:
    """One RemoteDesktop session with a keyboard and a pointer, started when the first event is sent."""

    def __init__(self, connect=open_connection, record: Path | None = None, clock=time.monotonic):
        self._connect = connect
        self._record = record or _record_path()
        self._clock = clock
        self._lock = threading.RLock()
        self._connection = None
        self._session = None
        self._counter = 0

    # --- the portal protocol ----------------------------------------------------------
    def _token(self) -> str:
        self._counter += 1
        return f'tessera{os.getpid()}x{self._counter}'

    def _address(self, member: str, signature: str, body: tuple):
        from jeepney import DBusAddress, new_method_call
        return new_method_call(DBusAddress(PATH, bus_name=BUS, interface=INTERFACE), member, signature, body)

    def _request(self, member: str, signature: str, body_before: tuple, options: dict, wait: float):
        """Call a portal method that answers with a Request: the answer is the Response signal of that request.

        The signal is subscribed to before the call, with the request's own path (it follows from our token), or an
        answer that comes at once would be lost."""
        from jeepney import MatchRule, message_bus
        connection = self._connection
        token = options['handle_token'][1]
        sender = connection.unique_name.lstrip(':').replace('.', '_')
        request_path = f'/org/freedesktop/portal/desktop/request/{sender}/{token}'
        rule = MatchRule(type='signal', interface=REQUEST, member='Response', path=request_path)
        connection.send_and_get_reply(message_bus.AddMatch(rule))
        with connection.filter(rule) as responses:
            checked(connection.send_and_get_reply(self._address(member, signature, (*body_before, options))))
            try:
                reply = connection.recv_until_filtered(responses, timeout=wait)
            except TimeoutError as exc:
                raise BackendUnavailable('The desktop did not answer the request for keyboard and mouse control. '
                                         'Answer the dialog, then press the key again.') from exc
        code, results = reply.body
        if code != 0:
            raise BackendUnavailable('Keyboard and mouse control was not allowed (the dialog was cancelled or '
                                     'refused). Press the key again to be asked once more.')
        return results

    def _saved_token(self) -> str | None:
        try:
            token = json.loads(self._record.read_text(encoding='utf-8')).get('restore_token')
            return token if isinstance(token, str) and token else None
        except (OSError, ValueError, AttributeError):
            return None

    def _save_token(self, token: str) -> None:
        try:
            temporary = self._record.with_suffix('.tmp')
            temporary.write_text(json.dumps({'restore_token': token}), encoding='utf-8')
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._record)
        except OSError:
            log.debug('could not remember the remote desktop permission', exc_info=True)

    def start(self) -> None:
        """Open the connection and the session; shows the permission dialog the first time."""
        with self._lock:
            self.close()
            self._connection = self._connect()
            try:
                created = self._request('CreateSession', 'a{sv}', (), {
                    'handle_token': ('s', self._token()), 'session_handle_token': ('s', self._token())}, RESPONSE_WAIT)
                self._session = created['session_handle'][1]
                select = {'handle_token': ('s', self._token()), 'types': ('u', KEYBOARD | POINTER),
                          'persist_mode': ('u', PERSIST_UNTIL_REVOKED)}
                token = self._saved_token()
                if token:
                    select['restore_token'] = ('s', token)
                self._request('SelectDevices', 'oa{sv}', (self._session,), select, RESPONSE_WAIT)
                started = self._request('Start', 'osa{sv}', (self._session, ''),
                                        {'handle_token': ('s', self._token())}, DIALOG_WAIT)
                new_token = started.get('restore_token')
                if new_token:
                    self._save_token(new_token[1])
                granted = started.get('devices', ('u', 0))[1]
                if not granted & KEYBOARD:
                    raise BackendUnavailable('The desktop did not give Tessera the keyboard.')
            except BaseException:
                self.close()
                raise

    def close(self) -> None:
        with self._lock:
            connection, self._connection, self._session = self._connection, None, None
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass

    # --- events -----------------------------------------------------------------------------
    def _notify(self, member: str, signature: str, *arguments) -> None:
        """Send one input event. A session that has ended (the desktop closed it, the bus dropped) is started again once."""
        with self._lock:
            for attempt in (1, 2):
                if self._session is None:
                    self.start()
                try:
                    from jeepney import DBusAddress, new_method_call
                    address = DBusAddress(PATH, bus_name=BUS, interface=INTERFACE)
                    checked(self._connection.send_and_get_reply(
                        new_method_call(address, member, f'o{signature}', (self._session, *arguments)), timeout=RESPONSE_WAIT))
                    return
                except BackendUnavailable:
                    raise
                except Exception as exc:  # DBusErrorResponse, a closed socket ...
                    self.close()
                    if attempt == 2:
                        raise OSError(f'The desktop refused the input: {exc}') from exc

    def keysym(self, number: int, pressed: bool) -> None:
        self._notify('NotifyKeyboardKeysym', 'a{sv}iu', {}, number, 1 if pressed else 0)

    def button(self, name: str, pressed: bool) -> None:
        self._notify('NotifyPointerButton', 'a{sv}iu', {}, BUTTONS[name], 1 if pressed else 0)

    def scroll(self, steps: int) -> None:
        """Wheel notches; positive is up, as on Windows."""
        self._notify('NotifyPointerAxisDiscrete', 'a{sv}ui', {}, AXIS_VERTICAL, -int(steps))

    def move(self, dx: float, dy: float) -> None:
        self._notify('NotifyPointerMotion', 'a{sv}dd', {}, float(dx), float(dy))

