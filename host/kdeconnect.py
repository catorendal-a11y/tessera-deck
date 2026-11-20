"""Other devices of the user that KDE Connect has paired (a phone, a laptop): their media player and its volume.

KDE Connect's daemon (`kdeconnectd`) is on a D-Bus as org.kde.kdeconnect: the session bus on Linux, a bus of its own on
Windows. A device that can be controlled has an `mprisremote` object with the player's `volume` (writable), `isPlaying`,
`title` and `artist`, and a `sendAction` method. What is asked is the same on both systems; the platform modules
(platform_linux/remote.py, platform_windows/remote.py) only bring the bus. Without KDE Connect the list is simply empty.

The four calls the shared code uses (host/remote_devices.py): list_devices, read_device, write_volume, send_action.
"""
from __future__ import annotations

import logging
import time

from dbus_client import DBusError, NotRunning

log = logging.getLogger(__name__)

NAME = 'org.kde.kdeconnect'
DAEMON = ('/modules/kdeconnect', 'org.kde.kdeconnect.daemon')
DEVICE = 'org.kde.kdeconnect.device'
REMOTE = 'org.kde.kdeconnect.device.mprisremote'
PLUGIN = 'kdeconnect_mprisremote'
PROPERTIES = 'org.freedesktop.DBus.Properties'
ACTIONS = ('PlayPause', 'Play', 'Pause', 'Next', 'Previous', 'Stop')  # what sendAction takes
TIMEOUT = 1.0  # seconds a call may take: the host asks from its 1 Hz loop
BACK_OFF = 10.0  # after a failure the daemon is left alone for this long
ABSENT_BACK_OFF = 60.0  # and when it is not running at all (on Windows each look for it scans the processes)
LIST_SECONDS = 5.0  # devices come and go rarely
READ_SECONDS = 1.0  # the mixer and the label variables share one read


def _value(variant):
    return variant[1] if isinstance(variant, tuple) else variant


def _seconds(variant) -> float:
    """KDE Connect reports the position and the length of a track in milliseconds."""
    value = _value(variant) if variant is not None else 0
    return max(0.0, float(value) / 1000) if isinstance(value, (int, float)) else 0.0


def _path(device: str, plugin: str = '') -> str:
    return f'/modules/kdeconnect/devices/{device}' + (f'/{plugin}' if plugin else '')


class KdeConnect:
    """The questions to kdeconnectd over `bus` (anything with call() and close(), see host/dbus_client.py), with a short
    cache and a back-off so that a daemon or a device that does not answer cannot stall the host's 1 Hz loop."""

    def __init__(self, bus, clock=time.monotonic):
        self.bus = bus
        self.clock = clock
        self._cache: dict = {}
        self._failed: dict = {}  # what was asked -> until when it is left alone after a failure
        self._writes = 0  # counts the writes: a read that began before one must not be kept, it may show the old value

    def _call(self, path, interface, member, signature='', body=()):
        return self.bus.call(NAME, path, interface, member, signature, body)

    def _cached(self, key, seconds, load):
        """`load()` at most every `seconds`. After a failure that question is left alone for BACK_OFF seconds, and for longer
        when KDE Connect is not running. Raises OSError then. The connection is not closed here: a bus closes itself when
        the connection broke, and an error reply of one device must not take the others' calls with it."""
        now = self.clock()
        if now < self._failed.get(key, 0.0):
            raise OSError('KDE Connect is not answering')
        hit = self._cache.get(key)
        if hit and now - hit[0] < seconds:
            return hit[1]
        writes = self._writes
        try:
            value = load()
        except OSError as exc:
            self._failed[key] = now + (ABSENT_BACK_OFF if isinstance(exc, NotRunning) else BACK_OFF)
            self._cache.pop(key, None)
            raise
        self._failed.pop(key, None)
        if writes == self._writes:
            self._cache[key] = (now, value)
        return value

    def _written(self, device: str) -> None:
        self._writes += 1
        self._cache.pop(('read', device), None)

    def reset(self) -> None:
        """Forget what was read and any back-off (a new connection, or a test)."""
        self._failed.clear()
        self._cache.clear()
        self.bus.close()

    def list_devices(self) -> list[dict]:
        """Paired devices that are reachable now and can be asked about their media: [{'id', 'name', 'type'}]. Empty
        without KDE Connect (no daemon is not an error)."""
        def load():
            ids = self._call(DAEMON[0], DAEMON[1], 'devices', 'bb', (True, True))[0]
            found = []
            for device in ids:
                try:
                    plugins = self._call(_path(device), DEVICE, 'loadedPlugins')[0]
                    if PLUGIN not in plugins:
                        continue
                    properties = self._call(_path(device), PROPERTIES, 'GetAll', 's', (DEVICE,))[0]
                except DBusError as exc:  # no such object: the device went away while the list was made, the others are still good
                    log.debug('KDE Connect: %s: %s', device, exc)
                    continue  # (a timeout, a lost connection or an absent daemon ends the list and is backed off by _cached)
                found.append({'id': device, 'name': str(_value(properties.get('name', ('s', device)))),
                              'type': str(_value(properties.get('type', ('s', ''))))})
            return found
        try:
            return self._cached('devices', LIST_SECONDS, load)
        except OSError as exc:
            log.debug('KDE Connect: %s', exc)
            return []

    def read_device(self, device: str) -> dict:
        """{'volume': 0-100 or None, 'playing': bool, 'title', 'artist', 'position', 'duration'} (seconds) of the device's
        selected player; OSError when it fails."""
        def load():
            properties = self._call(_path(device, 'mprisremote'), PROPERTIES, 'GetAll', 's', (REMOTE,))[0]
            volume = _value(properties.get('volume', ('i', None)))
            return {'volume': max(0, min(100, int(volume))) if isinstance(volume, (int, float)) else None,
                    'playing': bool(_value(properties.get('isPlaying', ('b', False)))),
                    'title': str(_value(properties.get('title', ('s', ''))) or ''),
                    'artist': str(_value(properties.get('artist', ('s', ''))) or ''),
                    'position': _seconds(properties.get('position')), 'duration': _seconds(properties.get('length'))}
        return self._cached(('read', device), READ_SECONDS, load)

    def write_volume(self, device: str, level: int) -> None:
        """Set the volume of the device's selected player (0-100)."""
        level = max(0, min(100, int(level)))
        try:
            self._call(_path(device, 'mprisremote'), PROPERTIES, 'Set', 'ssv', (REMOTE, 'volume', ('i', level)))
        finally:
            self._written(device)  # the next read shows what the device did with it

    def send_action(self, device: str, action: str) -> None:
        """PlayPause, Play, Pause, Next, Previous or Stop for the device's selected player."""
        if action not in ACTIONS:
            raise ValueError(f'Unknown remote media action: {action}')
        try:
            self._call(_path(device, 'mprisremote'), REMOTE, 'sendAction', 's', (action,))
        finally:
            self._written(device)
