"""A blocking D-Bus connection (jeepney, a pure Python client): the shared half of platform_linux/dbus.py (the session bus) and
platform_windows/dbus.py (the bus KDE Connect starts for itself). A subclass only says how the connection is opened.

jeepney hands an error reply back like any other reply, so `call` turns it into an OSError: a call that failed must not look
as if it had worked.
"""
from __future__ import annotations

TIMEOUT = 2.0


class Bus:
    """One lazily opened connection; any error closes it so the next call connects again."""

    def __init__(self, timeout: float = TIMEOUT):
        self._connection = None
        self.timeout = timeout

    def _open(self):
        """A new jeepney DBusConnection (jeepney.io.blocking). Raises OSError when there is no bus to reach."""
        raise NotImplementedError

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except OSError:
                pass
            self._connection = None

    def connect(self):
        if self._connection is None:
            try:
                import jeepney  # noqa: F401
            except ImportError as exc:
                raise OSError(f'this needs the "jeepney" package: {exc}') from exc
            self._connection = self._open()
        return self._connection

    def call(self, destination, path, interface, member, signature='', body=(), timeout=None):
        """The body of the reply. Raises OSError for an error reply, a timeout or a lost connection."""
        from jeepney import DBusAddress, MessageType, new_method_call
        address = DBusAddress(path, bus_name=destination, interface=interface)
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
            raise OSError(f'{header.fields.get(HeaderFields.error_name, "D-Bus error")}: {reply.body[0] if reply.body else ""}')
        return reply.body
