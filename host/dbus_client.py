"""A blocking D-Bus connection (jeepney, a pure Python client): the shared half of platform_linux/dbus.py (the session bus) and
platform_windows/dbus.py (the bus KDE Connect starts for itself). A subclass only says how the connection is opened.

jeepney hands an error reply back like any other reply, so `call` turns it into an OSError: a call that failed must not look
as if it had worked.
"""
from __future__ import annotations

import socket
import threading

TIMEOUT = 2.0
HELLO_SECONDS = 3.0  # jeepney waits for the bus's answer to Hello without any limit
# What the bus says when nobody has the name: the program (KDE Connect) is not running
ABSENT = ('org.freedesktop.DBus.Error.ServiceUnknown', 'org.freedesktop.DBus.Error.NameHasNoOwner')


def open_connection(sock: socket.socket, hello_seconds: float = HELLO_SECONDS):
    """A jeepney DBusConnection on `sock`, which is already signed in, that says Hello within `hello_seconds`. jeepney's own
    DBusConnection waits for the answer without any limit, which the socket's timeout does not shorten (it waits in a select), so a
    bus that stays silent would hold the host's loop for ever. Past the time the socket is closed and the caller gets an OSError."""
    from jeepney.io.blocking import DBusConnection, DBusConnectionBase, MessageFilters, Proxy, message_bus

    class Connection(DBusConnection):
        def __init__(self):
            DBusConnectionBase.__init__(self, sock)  # not DBusConnection's: that one says Hello without a time limit
            self._filters = MessageFilters()
            self.bus_proxy = Proxy(message_bus, self, timeout=hello_seconds)
            self.unique_name = self.bus_proxy.Hello()[0]
    try:
        return Connection()
    except TimeoutError as exc:
        sock.close()
        raise OSError(f'the D-Bus did not answer Hello within {hello_seconds:g} seconds') from exc
    except Exception as exc:
        sock.close()
        raise OSError(f'the D-Bus refused Hello: {exc}') from exc


class NotRunning(OSError):
    """The program that was asked is not running (as opposed to one that failed): worth asking again only after a while."""


class Bus:
    """One lazily opened connection; any error closes it so the next call connects again."""

    def __init__(self, timeout: float = TIMEOUT):
        self._connection = None
        self.timeout = timeout
        # A blocking connection is not for two threads at once (replies get mixed up, a close pulls the socket away): the poll
        # thread, the 1 Hz loop and the job thread all ask, so one call at a time.
        self._lock = threading.RLock()

    def _open(self):
        """A new jeepney DBusConnection (jeepney.io.blocking). Raises OSError when there is no bus to reach."""
        raise NotImplementedError

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except OSError:
                    pass
                self._connection = None

    def connect(self):
        with self._lock:
            if self._connection is None:
                try:
                    import jeepney  # noqa: F401
                except ImportError as exc:
                    raise OSError(f'this needs the "jeepney" package: {exc}') from exc
                self._connection = self._open()
            return self._connection

    def call(self, destination, path, interface, member, signature='', body=(), timeout=None):
        """The body of the reply. Raises OSError for an error reply, a timeout or a lost connection, and NotRunning when nobody
        has `destination`."""
        from jeepney import DBusAddress, MessageType, new_method_call
        address = DBusAddress(path, bus_name=destination, interface=interface)
        with self._lock:
            try:
                reply = self.connect().send_and_get_reply(new_method_call(address, member, signature, body),
                                                          timeout=timeout or self.timeout)
            except TimeoutError as exc:
                self.close()
                raise OSError(f'{destination} did not answer') from exc
            except OSError:  # the connection broke (the daemon quit): the next call connects again
                self.close()
                raise
        header = getattr(reply, 'header', None)
        if header is not None and header.message_type == MessageType.error:
            from jeepney.low_level import HeaderFields
            name = header.fields.get(HeaderFields.error_name, 'D-Bus error')
            message = f'{name}: {reply.body[0] if reply.body else ""}'
            raise (NotRunning if name in ABSENT else OSError)(message)  # a reply: the connection is fine
        return reply.body
