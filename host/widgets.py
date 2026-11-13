"""Ready-made widgets for wide keys: what a key two or three slots wide shows besides its own title.

Each widget is a title, a second line and, where it means something, how full a bar or ring is (0-100).
The panel draws all of them the same way, so a new widget needs no new firmware.
"""
from datetime import datetime

# kind -> (name in the editor, icon, suggested width)
WIDGETS = {
    'clock': ('Clock', 'lc:e087', 2),
    'date': ('Date', 'lc:e063', 2),
    'cpu': ('Processor', 'lc:e0a9', 2),
    'gpu': ('Graphics card', 'lc:e11d', 2),
    'ram': ('Memory', 'lc:e445', 2),
    'network': ('Network', 'lc:e046', 2),
    'volume': ('Volume', 'lc:e1ab', 2),
    'agents': ('AI agents', 'lc:e1bb', 3),
}


def _percent(value) -> int:
    return max(0, min(100, round(value)))


def _rate(value: float) -> str:
    """Bytes per second in the unit that reads best."""
    for unit, size in (('GB/s', 1 << 30), ('MB/s', 1 << 20), ('kB/s', 1 << 10)):
        if value >= size:
            return f'{value / size:.1f} {unit}'
    return f'{value:.0f} B/s'


def _load(name: str, raw: dict, load: str, temp: str, extra: str = '') -> dict:
    value = raw.get(load)
    if value is None:
        return {'label': name, 'sub': 'No reading'}
    parts = [f'{raw[temp]:.0f} °C'] if raw.get(temp) is not None else []
    if extra:
        parts.append(extra)
    return {'label': f'{name} {value:.0f}%', 'sub': ' · '.join(parts) or 'Load', 'progress': _percent(value)}


def content(kind: str, now: datetime, raw: dict, audio: dict, agents: dict) -> dict:
    """The fields a wide key gets for this widget; an unknown kind gives nothing."""
    if kind == 'clock':
        day = (now.hour * 3600 + now.minute * 60 + now.second) / 864
        return {'label': now.strftime('%H:%M'), 'sub': now.strftime('%A %d %b').replace(' 0', ' '), 'progress': _percent(day)}
    if kind == 'date':
        # a two-slot key has 162 px: the weekday moves to the second line so the title fits in the large type
        return {'label': now.strftime('%d %b').lstrip('0'), 'sub': f'{now.strftime("%A")} · week {now.isocalendar()[1]}'}
    if kind == 'cpu':
        clock = raw.get('cpu_clock')
        return _load('CPU', raw, 'cpu_load', 'cpu_temp', f'{clock / 1000:.1f} GHz' if clock else '')
    if kind == 'gpu':
        return _load('GPU', raw, 'gpu_load', 'gpu_temp', f'{raw["fps"]:.0f} fps' if raw.get('fps') else '')
    if kind == 'ram':
        value = raw.get('ram')
        return {'label': 'RAM', 'sub': 'No reading'} if value is None else {'label': f'RAM {value:.0f}%', 'sub': 'Memory in use', 'progress': _percent(value)}
    if kind == 'network':
        return {'label': _rate(raw.get('net_down') or 0), 'sub': 'Up ' + _rate(raw.get('net_up') or 0)}  # the title is the download; the panel font has no arrows
    if kind == 'volume':
        level = audio.get('volume')
        if level is None:
            return {'label': 'Volume', 'sub': 'No sound device'}
        return {'label': 'Muted' if audio.get('speaker_muted') else f'{level}%',
                'sub': 'Volume · mic off' if audio.get('mic_muted') else 'Volume · mic on', 'progress': _percent(level)}
    if kind == 'agents':
        waiting = [name for name, state in agents.items() if state == 'waiting']
        working = [name for name, state in agents.items() if state == 'working']
        if waiting:
            return {'label': f'{len(waiting)} waiting for you', 'sub': ', '.join(waiting)[:40]}
        if working:
            return {'label': f'{len(working)} working', 'sub': ', '.join(working)[:40]}
        return {'label': 'Agents idle', 'sub': 'Nothing is running'}
    return {}
