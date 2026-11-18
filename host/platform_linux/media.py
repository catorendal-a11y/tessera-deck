"""The current media session on Linux: any MPRIS player (Spotify, browsers, VLC, mpv ...) on the session bus.

Same result as pc_state.MediaReader on Windows. Uses `jeepney`, a pure Python D-Bus client that the keyring already
needs, so there is no extra system tool.
"""
from __future__ import annotations

MPRIS = 'org.mpris.MediaPlayer2.'
PATH = '/org/mpris/MediaPlayer2'
PLAYER = 'org.mpris.MediaPlayer2.Player'
EMPTY = {'title': '', 'artist': '', 'status': '', 'position': 0.0, 'duration': 0.0}
STATUS = {'Playing': 'PLAYING', 'Paused': 'PAUSED', 'Stopped': 'STOPPED'}
RANK = {'PLAYING': 0, 'PAUSED': 1, 'STOPPED': 2}  # the player that plays wins, then a paused one


def _value(variant):
    return variant[1] if isinstance(variant, tuple) else variant


def describe(properties: dict) -> dict:
    """One player's GetAll answer as the media dict; `properties` maps names to D-Bus (signature, value) pairs."""
    meta = {key: _value(value) for key, value in (_value(properties.get('Metadata', ('a{sv}', {}))) or {}).items()}
    artist = meta.get('xesam:artist', '')
    artist = ', '.join(artist) if isinstance(artist, (list, tuple)) else str(artist or '')
    length = meta.get('mpris:length', 0)
    position = _value(properties.get('Position', ('x', 0)))
    return {'title': str(meta.get('xesam:title', '') or ''), 'artist': artist,
            'status': STATUS.get(_value(properties.get('PlaybackStatus', ('s', ''))), ''),
            'position': float(position) / 1_000_000 if isinstance(position, (int, float)) else 0.0,
            'duration': float(length) / 1_000_000 if isinstance(length, (int, float)) else 0.0}


def choose(sessions: list[dict]) -> dict:
    return min(sessions, key=lambda item: RANK.get(item['status'], 3)) if sessions else dict(EMPTY)


class MediaReader:
    """Reads the current media session; raises OSError when there is no session bus."""

    def __init__(self):
        self._connection = None

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _connect(self):
        try:
            from jeepney.io.blocking import open_dbus_connection
        except ImportError as exc:
            raise OSError(f'media control needs the "jeepney" package: {exc}') from exc
        if self._connection is None:
            try:
                self._connection = open_dbus_connection(bus='SESSION')
            except (OSError, KeyError) as exc:  # no session bus (no DBUS_SESSION_BUS_ADDRESS)
                raise OSError(f'no D-Bus session bus: {exc}') from exc
        return self._connection

    def _call(self, destination, path, interface, member, signature='', body=()):
        from jeepney import DBusAddress, new_method_call
        address = DBusAddress(path, bus_name=destination, interface=interface)
        reply = self._connect().send_and_get_reply(new_method_call(address, member, signature, body), timeout=2)
        return reply.body

    def __call__(self) -> dict:
        try:
            names = self._call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'ListNames')[0]
            sessions = []
            for name in names:
                if not name.startswith(MPRIS):
                    continue
                try:
                    properties = self._call(name, PATH, 'org.freedesktop.DBus.Properties', 'GetAll', 's', (PLAYER,))[0]
                except Exception:  # a player that quit between the list and the question
                    continue
                sessions.append(describe(properties))
        except OSError:
            self.close()  # the bus went away: connect again on the next poll
            raise
        except Exception as exc:
            self.close()
            raise OSError(f'media session unavailable: {exc}') from exc
        return choose(sessions)


# --- changing a player's options (shuffle, repeat): the `media` action ---------------------------------------------

REPEAT_CYCLE = {'None': 'Playlist', 'Playlist': 'Track', 'Track': 'None'}  # off, all, one, off: as on Windows


def _property(reader: 'MediaReader', name: str, prop: str):
    """One property of the player's Player interface; None when the player does not have it."""
    try:
        body = reader._call(name, PATH, 'org.freedesktop.DBus.Properties', 'Get', 'ss', (PLAYER, prop))
    except Exception:
        return None
    return _value(body[0]) if body else None


def control_media(operation: str, reader: 'MediaReader | None' = None) -> None:
    """Toggle shuffle or cycle repeat in the current media session. A player without it is left alone, and the
    OSError says so: otherwise the key would report success for a press that changed nothing."""
    from pc_state import check_media
    check_media({'op': operation})
    reader = reader or MediaReader()
    try:
        names = [name for name in reader._call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                                               'ListNames')[0] if name.startswith(MPRIS)]
        best = None
        for name in names:  # the player that plays wins, then a paused one, as for the status screen
            status = STATUS.get(_property(reader, name, 'PlaybackStatus') or '', '')
            if best is None or RANK.get(status, 3) < best[0]:
                best = (RANK.get(status, 3), name)
        if best is None:
            raise OSError('No player is open (no MPRIS media player was found)')
        name = best[1]
        if _property(reader, name, 'CanControl') is False:
            raise OSError(f'This player does not offer {operation}')
        if operation == 'shuffle':
            current = _property(reader, name, 'Shuffle')
            new = ('b', not current)
            prop = 'Shuffle'
        else:
            current = _property(reader, name, 'LoopStatus')
            if current not in REPEAT_CYCLE:
                raise OSError(f'This player does not offer {operation}')
            new = ('s', REPEAT_CYCLE[current])
            prop = 'LoopStatus'
        if current is None:
            raise OSError(f'This player does not offer {operation}')
        reader._call(name, PATH, 'org.freedesktop.DBus.Properties', 'Set', 'ssv', (PLAYER, prop, new))
    except OSError:
        raise
    except Exception as exc:
        raise OSError(f'The media player refused {operation}: {exc}') from exc
    finally:
        reader.close()
