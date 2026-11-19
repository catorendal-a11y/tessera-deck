"""Other devices paired with KDE Connect (a phone, a laptop): the volume of their media player as a fader of the mixer, and
their media keys. What the system provides (platform_linux/remote.py, platform_windows/remote.py; both ask host/kdeconnect.py) is four calls: list_devices, read_device,
write_volume and send_action. Choosing the devices, the fader ids and what a mute does are the same everywhere.

The panel shows at most five faders, an id of at most 39 characters and a name of 15, so a device is named by `remote:` and ten
characters of its id's hash.
"""
from __future__ import annotations

import hashlib
import re

from platform_support import load

MODES = ('off', 'first', 'all', 'device')
FADER_PREFIX = 'remote:'
COLOR = '#FF8A65'
NAME_LENGTH = 15  # the panel cuts a fader's name there
RESTORE_LEVEL = 50  # what a muted device gets back when nothing was remembered
MEDIA_OPS = {'playpause': 'PlayPause', 'play': 'Play', 'pause': 'Pause', 'next': 'Next', 'previous': 'Previous', 'stop': 'Stop'}
VOLUME_OPS = ('volumeup', 'volumedown')  # the device's volume, a step at a time
OPS = (*MEDIA_OPS, *VOLUME_OPS)
DEFAULT_STEP = 5
DEVICE_ID = re.compile(r'[A-Za-z0-9_.-]{1,64}')
NO_DEVICE = 'No paired device with media control is reachable. Is KDE Connect running and the device connected?'

_muted: dict[str, int] = {}  # short id -> the volume before it was muted
EMPTY_STATE = {'remote:track': '', 'remote:artist': '', 'remote_playing': False, 'remote_status': '', 'remote_position': 0.0,
               'remote_duration': 0.0}


def _system():
    return load('remote')


def short_id(device_id: str) -> str:
    return hashlib.sha1(device_id.encode('utf-8')).hexdigest()[:10]


def devices() -> list[dict]:
    """The reachable, paired devices that can be controlled: [{'id', 'short', 'name', 'type'}]."""
    try:
        found = _system().list_devices()
    except OSError:
        return []
    return [dict(device, short=short_id(device['id'])) for device in found]


def select(found: list[dict], mode: str = 'first', device: str | None = None) -> list[dict]:
    """The devices a setting means: 'first', 'all' (the mixer only), or one device by its id."""
    if mode == 'all':
        return list(found)
    if mode == 'device' and device:
        return [item for item in found if device in (item['id'], item['short'])]
    return found[:1]


def _setting(setting) -> tuple[str, str | None]:
    setting = setting if isinstance(setting, dict) else {}
    return setting.get('mode', 'off'), setting.get('device')


def faders(setting) -> list[dict]:
    """The mixer faders of the chosen devices (none when the setting is off or nothing is reachable)."""
    mode, device = _setting(setting)
    if mode == 'off':
        return []
    found = []
    for item in select(devices(), mode, device):
        try:
            volume = _system().read_device(item['id'])['volume']
        except (OSError, KeyError):
            continue
        if volume is not None:
            found.append({'id': FADER_PREFIX + item['short'], 'name': item['name'][:NAME_LENGTH], 'level': volume,
                          'muted': volume == 0, 'color': COLOR})
    return found


def is_fader(fader_id: str) -> bool:
    return isinstance(fader_id, str) and fader_id.startswith(FADER_PREFIX)


def _device_of(fader_id: str) -> dict:
    short = fader_id.removeprefix(FADER_PREFIX)
    for item in devices():
        if item['short'] == short:
            return item
    raise OSError('That device is not reachable')


def set_volume(fader_id: str, level: int) -> None:
    item = _device_of(fader_id)
    _muted.pop(item['short'], None)
    _system().write_volume(item['id'], max(0, min(100, int(level))))


def toggle_mute(fader_id: str) -> None:
    """The panel always shows a mute button: a device has no mute, so this sets 0 and, the second time, the old volume."""
    item = _device_of(fader_id)
    current = _system().read_device(item['id'])['volume'] or 0
    if current > 0:
        _muted[item['short']] = current
        _system().write_volume(item['id'], 0)
    else:
        _system().write_volume(item['id'], _muted.pop(item['short'], RESTORE_LEVEL))


def control_media(op: str, device: str = 'first', step: int = DEFAULT_STEP) -> None:
    """Play/pause, next, previous ... or the volume up or down by `step` percent, on the first reachable device or on one device
    (by id); OSError when it cannot be reached."""
    if op not in OPS:
        raise ValueError(f'remote media: op must be one of {", ".join(OPS)}')
    found = devices()
    chosen = select(found, 'first' if device == 'first' else 'device', device)
    if not chosen:
        raise OSError(NO_DEVICE if not found else 'That device is not reachable')
    item = chosen[0]
    try:
        if op in VOLUME_OPS:
            current = _system().read_device(item['id'])['volume']
            if current is None:
                raise OSError('it does not report a volume')
            _muted.pop(item['short'], None)
            _system().write_volume(item['id'], max(0, min(100, current + (step if op == 'volumeup' else -step))))
        else:
            _system().send_action(item['id'], MEDIA_OPS[op])
    except OSError as exc:
        raise OSError(f'{item["name"]}: {exc}') from exc


def state(setting) -> dict:
    """What PcState keeps of the first chosen device: $(remote:track), $(remote:artist), the flag `remote_playing` that a key can
    follow (bind), and what a wide key shows (the status, how far the track is). Empty and False when no device is reachable."""
    mode, device = _setting(setting)
    for item in select(devices(), 'first' if mode == 'off' else mode, device)[:1]:
        try:
            read = _system().read_device(item['id'])
        except OSError:
            break
        return {'remote:track': read['title'], 'remote:artist': read['artist'], 'remote_playing': bool(read['playing']),
                'remote_status': 'PLAYING' if read['playing'] else 'PAUSED' if read['title'] else '',
                'remote_position': read.get('position', 0.0), 'remote_duration': read.get('duration', 0.0)}
    return dict(EMPTY_STATE)


def check_device(value) -> str:
    """A device choice of an action: 'first' or a device id. An action reaches one device, never every one."""
    if value == 'first' or (isinstance(value, str) and value != 'all' and DEVICE_ID.fullmatch(value)):
        return value
    raise ValueError('device is first or the id of a paired device')


def check_setting(setting) -> None:
    """The `remote` block of the panel configuration: {"mode": off|first|all|device, "device": id}."""
    if not isinstance(setting, dict) or set(setting) - {'mode', 'device'}:
        raise ValueError('panel.remote must be an object with mode and device')
    mode = setting.get('mode', 'off')
    if mode not in MODES:
        raise ValueError(f'panel.remote.mode must be one of {", ".join(MODES)}')
    if mode == 'device':
        if not isinstance(setting.get('device'), str) or not DEVICE_ID.fullmatch(setting['device']):
            raise ValueError('panel.remote.device must be the id of a paired device')
    elif 'device' in setting:
        raise ValueError('panel.remote.device is only used with the mode "device"')
