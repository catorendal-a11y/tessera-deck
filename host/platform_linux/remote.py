"""Other devices of the user that KDE Connect has paired (a phone, a laptop), on Linux: kdeconnectd is on the session bus.

What is asked is shared with Windows (host/kdeconnect.py). Nothing here needs an extra tool: the host talks D-Bus itself
(jeepney). The four functions the shared code uses (host/remote_devices.py): list_devices, read_device, write_volume,
send_action.
"""
from __future__ import annotations

from kdeconnect import TIMEOUT, KdeConnect
from platform_linux.dbus import SessionBus

client = KdeConnect(SessionBus(TIMEOUT))


def list_devices() -> list[dict]:
    return client.list_devices()


def read_device(device: str) -> dict:
    return client.read_device(device)


def write_volume(device: str, level: int) -> None:
    client.write_volume(device, level)


def send_action(device: str, action: str) -> None:
    client.send_action(device, action)


def reset() -> None:
    client.reset()
