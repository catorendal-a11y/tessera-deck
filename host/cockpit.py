"""The panel's cockpit screens (protocol 4): what the host sends for the agents, the mixer and the PC's readings.

Each screen is one JSON line (AD_AGENTS, AD_MIXER, AD_STATS) that the panel redraws from. The panel keeps a line in
a 1100-byte buffer, so every payload here is built to stay well below that.
"""
from __future__ import annotations

import json

PROTOCOL = 4
MAX_LINE = 1000
MAX_ID = 39  # DECK_ID_MAX in main/deck_model.h: the panel refuses a longer id
AGENTS = (('claude', 'Claude Code', 'claude.exe'), ('codex', 'Codex', 'codex.exe'), ('zcode', 'ZCode', 'zcode.exe'))
AGENT_ACTIONS = ('allow', 'deny', 'stop', 'open')
APP_COLORS = ('#B388FF', '#F2B94B', '#7C8CF8')
MAX_APPS = 3
GREEN, BLUE, PURPLE, GREY, AMBER, RED = '#58E09B', '#64B5F6', '#B388FF', '#A3B2BC', '#FFB74D', '#FF7070'
# (label, sensor key, unit, value that fills the bar, warn from, colour)
STATS = (('CPU load', 'cpu_load', '%', 100, 95, GREEN), ('CPU temp', 'cpu_temp', 'C', 100, 85, GREEN),
         ('RAM', 'ram', '%', 100, 90, BLUE), ('Disk', 'disk', '%', 100, 90, BLUE),
         ('GPU load', 'gpu_load', '%', 100, None, PURPLE), ('GPU temp', 'gpu_temp', 'C', 100, 85, PURPLE),
         ('VRAM', 'vram', '%', 100, 90, PURPLE), ('Download', 'net_down', '/s', 10 * 1024 * 1024, None, GREY),
         ('Upload', 'net_up', '/s', 10 * 1024 * 1024, None, GREY), ('Uptime', 'uptime', '', 7 * 86400, None, GREY),
         ('CPU clock', 'cpu_clock', 'MHz', 6000, None, GREEN), ('CPU power', 'cpu_power', 'W', 250, None, GREEN),
         ('GPU power', 'gpu_power', 'W', 450, None, PURPLE), ('GPU clock', 'gpu_clock', 'MHz', 3000, None, PURPLE),
         ('GPU fan', 'gpu_fan', 'RPM', 3000, None, PURPLE), ('FPS', 'fps', '', 144, None, BLUE))
STAT_IDS = tuple(key for _, key, *_ in STATS)
DEFAULT_STATS = STAT_IDS[:8]  # what the status screen shows until the user picks readings
MAX_STATS = 8  # DECK_STATS_MAX in main/deck_model.h


def _line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(',', ':'))


def agent_exe(agent_id: str) -> str:
    return next((exe for key, _, exe in AGENTS if key == agent_id), '')


SCREENS = ('keys', 'agents', 'mixer', 'status')
MAX_SHORTCUTS = 3
MAX_RAIL = 7


def rail_items(choice: dict, profiles: dict, actions: bool = True) -> list[dict]:
    """The rail's buttons: the chosen screens (Keys is always there) and shortcuts to pages that still exist."""
    screens = [name for name in choice.get('screens', SCREENS) if name in SCREENS]
    if 'keys' not in screens:
        screens.insert(0, 'keys')
    items = [{'k': name} for name in screens]
    for shortcut in choice.get('shortcuts', [])[:MAX_SHORTCUTS]:
        if shortcut.get('type') == 'actions':  # 'a' stays on the host; panel firmware before 0.6.3 refuses 'act'
            if actions:
                items.append({'k': 'act', 'i': shortcut.get('icon') or 'lc:e0ff', 'a': shortcut['actions']})
            continue
        profile = profiles.get(shortcut.get('profile'))
        if profile and shortcut.get('page') in profile.get('pages', {}):
            items.append({'k': 'page', 'i': shortcut.get('icon') or 'lc:e0ff', 'p': shortcut['profile'], 'g': shortcut['page']})
    return items[:MAX_RAIL]


def rail_payload(items: list[dict]) -> str:
    return _line({'rail': [{key: (value[:31] if key in ('p', 'g') else value) for key, value in item.items() if key != 'a'}
                           for item in items]})


def agents_payload(variables: dict, running: dict, asking: dict | None = None, shown: list | None = None,
                   since: dict | None = None) -> str:
    """One lane per AI tool that runs or has reported a state through its adapter (deckctl adapter ...).

    `since` maps an agent to the HH:MM it started working or waiting; the lane shows it as 'at'."""
    lanes = []
    since = since or {}
    for key, name, _ in AGENTS:
        if shown is not None and key not in shown:
            continue
        if asking and asking['agent'] == key:  # a permission prompt waiting for Allow or Deny on the panel
            # 'q' marks the one lane whose Allow/Deny answer something; a hook's 'waiting' (Claude asking in its
            # own dialog) has nothing to answer here, so the panel should offer Open for it instead.
            lanes.append({'id': key, 'name': name, 'state': 'waiting', 'text': asking['text'], 'q': 1,
                          'sub': str(variables.get(f'{key}.project', ''))[:30]})
            if since.get(key):
                lanes[-1]['at'] = since[key][:5]
            continue
        reported = str(variables.get(key, ''))
        if not running.get(key) and reported in ('', 'ended'):
            continue
        state = reported if reported in ('working', 'waiting') else 'idle'
        tool, message = str(variables.get(f'{key}.tool', '')), str(variables.get(f'{key}.message', ''))
        text = message or (f'Using {tool}' if tool and state == 'working' else 'Working' if state == 'working' else '')
        lanes.append({'id': key, 'name': name, 'state': state, 'text': text[:70],
                      'sub': str(variables.get(f'{key}.project', ''))[:30]})
        if state != 'idle' and since.get(key):
            lanes[-1]['at'] = since[key][:5]
    line = _line({'agents': lanes})
    if len(line) > MAX_LINE:  # only reachable with long non-ASCII text: shorten rather than be refused
        for lane in lanes:
            if not (asking and lane['id'] == asking['agent']):  # a permission question is never shown cut
                lane['text'] = lane['text'][:20]
            lane['sub'] = lane['sub'][:10]
        line = _line({'agents': lanes})
    return line


def stats_payload(display: dict, raw: dict, shown: list | None = None) -> str:
    """The readings for the status screen (the first eight unless `shown` picks, never more than eight); a missing sensor shows as --."""
    stats = []
    for label, key, unit, full, warn_from, color in STATS:
        if key not in (shown or DEFAULT_STATS) or len(stats) == MAX_STATS:
            continue
        value = raw.get(key)
        known = isinstance(value, (int, float))
        warn = known and warn_from is not None and value >= warn_from
        stats.append({'name': label, 'value': str(display.get(key, '--'))[:7], 'unit': unit,
                      'p': max(0, min(100, round(value / full * 100))) if known else 0,
                      'color': AMBER if warn else color, 'warn': bool(warn)})
    return _line({'stats': stats})


def app_title(process_name: str) -> str:
    """spotify.exe -> Spotify"""
    stem = process_name[:-4] if process_name.lower().endswith('.exe') else process_name
    return (stem[:1].upper() + stem[1:])[:15]


def read_mixer(pinned: list | None = None, mic: bool = True, remote: dict | None = None) -> list[dict]:
    """The default speaker, up to three programs and the microphone. Raises OSError without audio.

    `pinned` names the programs to show (those that have a sound session right now); without it the programs that
    play sound are chosen. The sound server of the system answers (platform_windows/audio.py, platform_linux/audio.py)."""
    import system_audio
    faders = system_audio.read_mixer(pinned, mic)
    import remote_devices
    extra = remote_devices.faders(remote)
    return fit_faders(faders, extra) if extra else faders


MAX_FADERS = 5  # DECK_FADERS_MAX in the firmware


def fit_faders(local: list[dict], remote: list[dict]) -> list[dict]:
    """The speaker, the remote devices, the programs and the microphone, in that order, in the five places the panel has. When
    they do not all fit, programs go first: the speaker, the remote devices the user chose and the microphone stay."""
    speaker = [item for item in local if item['id'] == 'speaker']
    mic = [item for item in local if item.get('mic')]
    apps = [item for item in local if item not in speaker and item not in mic]
    room = max(0, MAX_FADERS - len(speaker) - len(mic) - len(remote))
    return (speaker + remote + apps[:room] + mic)[:MAX_FADERS]


def mixer_payload(faders: list[dict]) -> str:
    return _line({'faders': faders})


