"""The D-Bus session bus (jeepney, which the keyring already needs): media players, KDE Connect. What a call does is shared
(host/dbus_client.py); here is only how the session bus is reached."""
from __future__ import annotations

from dbus_client import TIMEOUT, Bus


class SessionBus(Bus):
    def __init__(self, timeout: float = TIMEOUT):
        super().__init__(timeout)

    def _open(self):
        from jeepney.io.blocking import open_dbus_connection
        try:
            return open_dbus_connection(bus='SESSION')
        except (OSError, KeyError) as exc:  # no session bus (no DBUS_SESSION_BUS_ADDRESS)
            raise OSError(f'no D-Bus session bus: {exc}') from exc
