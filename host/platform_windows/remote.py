"""Other devices of the user that KDE Connect has paired (a phone, a laptop), on Windows: kdeconnectd is on the D-Bus that
KDE Connect for Windows starts for itself (platform_windows/dbus.py).

What is asked is shared with Linux (host/kdeconnect.py). The four functions the shared code uses (host/remote_devices.py):
list_devices, read_device, write_volume, send_action. Without KDE Connect running the list is simply empty.
"""
from __future__ import annotations

from kdeconnect import TIMEOUT, KdeConnect
from platform_windows.dbus import KdeConnectBus

client = KdeConnect(KdeConnectBus(TIMEOUT))


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
