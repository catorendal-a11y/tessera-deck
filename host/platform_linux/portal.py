"""Keyboard and pointer input on Wayland through the RemoteDesktop portal (org.freedesktop.portal.RemoteDesktop).

A Wayland compositor lets no program send keys on its own. The portal is the way the desktop offers: the program asks,
the desktop shows a dialog once, and from then on the session accepts key and pointer events. The permission is kept
(`persist_mode` 2 and a restore token in `host/remote-desktop.local.json`), so the dialog comes at the first key press
ever, not at every start of the host.

One session lives as long as its D-Bus connection, so the host keeps one connection and one session, and all calls take
a lock: the press threads of the host share it. `connect` is a parameter so the tests need no desktop.

The session is opened by a thread of its own, because the dialog can stay open for minutes and a key press holds the
host's state. The key that needs the session waits `START_GRACE` for it (a kept permission answers at once) and is
then refused with a message; the session is there for the next press once the dialog is answered.
"""
from __future__ import annotations

import itertools
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
EVENT_WAIT = 2.0  # seconds for one key or mouse event: the lock is held meanwhile, so a hung portal holds every press
DIALOG_WAIT = 120.0  # seconds the user has to answer the permission dialog
START_GRACE = 1.0  # seconds a key waits for the session before it is refused: enough where no dialog is shown
NOT_READY = ('Keyboard and mouse control through the desktop is not ready yet. If the desktop shows a dialog that asks '
             'for it, answer it, then press the key again.')
BUTTONS = {'left': 0x110, 'right': 0x111, 'middle': 0x112}  # Linux input event codes (BTN_LEFT ...)
AXIS_VERTICAL = 0


def _record_path() -> Path:
    return Path(__file__).resolve().parents[1] / 'remote-desktop.local.json'


def open_connection():
    """A blocking connection to the session bus (jeepney, which the host already needs for MPRIS). Signing in and Hello
    both have a time limit (dbus_client.open_connection): jeepney's own connection waits for Hello without one."""
    try:
        from jeepney.bus import get_bus
        from jeepney.io.blocking import prep_socket
    except ImportError as exc:
        raise BackendUnavailable('The jeepney package is missing: run Tessera.sh --setup') from exc
    from dbus_client import HELLO_SECONDS, open_connection as say_hello
    try:
        return say_hello(prep_socket(get_bus('SESSION'), timeout=HELLO_SECONDS))
    except (OSError, KeyError) as exc:  # KeyError: no session bus is named in the environment
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


class _Opening:
    """A session that is being opened by its own thread. All three are read and written with RemoteDesktop's lock held."""
    done = False
    error = None
    waited_for = False  # a key is waiting for it and reports the error itself


class RemoteDesktop:
    """One RemoteDesktop session with a keyboard and a pointer, started when the first event is sent."""

    def __init__(self, connect=open_connection, record: Path | None = None, clock=time.monotonic,
                 grace: float = START_GRACE):
        self._connect = connect
        self._record = record or _record_path()
        self._clock = clock
        self._grace = grace
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)  # an opening session is done
        self._connection = None
        self._session = None
        self._opening = None  # the _Opening on its way, or None
        self._counter = itertools.count(1)

    # --- the portal protocol ----------------------------------------------------------
    def _token(self) -> str:
        return f'tessera{os.getpid()}x{next(self._counter)}'

    def _address(self, member: str, signature: str, body: tuple):
        from jeepney import DBusAddress, new_method_call
        return new_method_call(DBusAddress(PATH, bus_name=BUS, interface=INTERFACE), member, signature, body)

    def _request(self, connection, member: str, signature: str, body_before: tuple, options: dict, wait: float):
        """Call a portal method that answers with a Request: the answer is the Response signal of that request.

        The signal is subscribed to before the call, with the request's own path (it follows from our token), or an
        answer that comes at once would be lost. `wait` is for that signal, which a dialog can hold back; the method
        replies before it have RESPONSE_WAIT, and a reply that does not come is a TimeoutError for the caller."""
        from jeepney import MatchRule, message_bus
        token = options['handle_token'][1]
        sender = connection.unique_name.lstrip(':').replace('.', '_')
        request_path = f'/org/freedesktop/portal/desktop/request/{sender}/{token}'
        rule = MatchRule(type='signal', interface=REQUEST, member='Response', path=request_path)
        connection.send_and_get_reply(message_bus.AddMatch(rule), timeout=RESPONSE_WAIT)
        with connection.filter(rule) as responses:
            checked(connection.send_and_get_reply(self._address(member, signature, (*body_before, options)),
                                                  timeout=RESPONSE_WAIT))
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
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # private before the token is in it
            with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
                file.write(json.dumps({'restore_token': token}))
            os.chmod(temporary, 0o600)  # a file left over by that name keeps its old mode through O_CREAT
            os.replace(temporary, self._record)
        except OSError:
            log.debug('could not remember the remote desktop permission', exc_info=True)

    def _open_session(self):
        """A new connection with a session on it, as (connection, session); shows the permission dialog the first time.
        It touches nothing of this object but the token counter and the record, so it runs without the lock."""
        connection = self._connect()
        try:
            created = self._request(connection, 'CreateSession', 'a{sv}', (), {
                'handle_token': ('s', self._token()), 'session_handle_token': ('s', self._token())}, RESPONSE_WAIT)
            session = created['session_handle'][1]
            select = {'handle_token': ('s', self._token()), 'types': ('u', KEYBOARD | POINTER),
                      'persist_mode': ('u', PERSIST_UNTIL_REVOKED)}
            token = self._saved_token()
            if token:
                select['restore_token'] = ('s', token)
            self._request(connection, 'SelectDevices', 'oa{sv}', (session,), select, RESPONSE_WAIT)
            started = self._request(connection, 'Start', 'osa{sv}', (session, ''),
                                    {'handle_token': ('s', self._token())}, DIALOG_WAIT)
            new_token = started.get('restore_token')
            if new_token:
                self._save_token(new_token[1])
            granted = started.get('devices', ('u', 0))[1]
            if not granted & KEYBOARD:
                raise BackendUnavailable('The desktop did not give Tessera the keyboard.')
            return connection, session
        except BaseException:
            self._hang_up(connection)
            raise

    @staticmethod
    def _hang_up(connection) -> None:
        try:
            connection.close()
        except OSError:
            pass

    def _open_in_background(self, opening: _Opening) -> None:
        connection = session = error = None
        try:
            connection, session = self._open_session()
        except Exception as exc:
            error = exc
        with self._lock:
            wanted = self._opening is opening  # close() came in between: this session is nobody's
            if wanted:
                self._opening = None
                self._connection, self._session = connection, session
            opening.error, opening.done = error, True
            heard = opening.waited_for
            self._changed.notify_all()
        if connection is not None and not wanted:
            self._hang_up(connection)
        if error is not None and not heard:  # the key that asked has gone: the log is where this can still be read
            log.warning('Keyboard and mouse control through the desktop was not started: %s', error)

    def _need_session(self) -> None:
        """With the lock held: return with a session, or raise. The session is opened by a thread of its own, one at a
        time; the key that starts it waits `grace` for it with the lock released, a key that finds it on its way does
        not wait at all. So a press never waits for the dialog."""
        if self._session is not None:
            return
        opening = self._opening
        if opening is None:
            opening = self._opening = _Opening()
            threading.Thread(target=self._open_in_background, args=(opening,), name='portal-session', daemon=True).start()
            opening.waited_for = True
            self._changed.wait_for(lambda: opening.done, self._grace)
            opening.waited_for = False
        if opening.error is not None:
            raise opening.error
        if self._session is None:
            raise BackendUnavailable(NOT_READY)

    def close(self) -> None:
        with self._lock:
            self._opening = None  # a session on its way is closed by its own thread when it arrives
            connection, self._connection, self._session = self._connection, None, None
            if connection is not None:
                self._hang_up(connection)

    # --- events -----------------------------------------------------------------------------
    def _notify(self, member: str, signature: str, *arguments) -> None:
        """Send one input event. A session that has ended (the desktop closed it, the bus dropped) is started again once."""
        with self._lock:
            for attempt in (1, 2):
                self._need_session()
                try:
                    from jeepney import DBusAddress, new_method_call
                    address = DBusAddress(PATH, bus_name=BUS, interface=INTERFACE)
                    checked(self._connection.send_and_get_reply(
                        new_method_call(address, member, f'o{signature}', (self._session, *arguments)), timeout=EVENT_WAIT))
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

