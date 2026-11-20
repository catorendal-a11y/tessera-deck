"""Speaker, microphone and per-program volume on Linux, through `pactl` (PulseAudio, or PipeWire's PulseAudio server).

The same four functions as the Windows side (pc_state.read_audio / control_audio, cockpit.read_mixer). The session
type does not matter here, so this module does not depend on the desktop backend.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from program_name import plain

TIMEOUT = 3.0
SINK, SOURCE = '@DEFAULT_SINK@', '@DEFAULT_SOURCE@'
PERCENT = re.compile(r'(\d+)%')


def pactl(*args: str) -> str:
    if shutil.which('pactl') is None:
        raise OSError('audio control needs pactl: install the "pulseaudio-utils" or "libpulse" package')
    try:
        done = subprocess.run(['pactl', *args], capture_output=True, text=True, timeout=TIMEOUT, check=False,
                              env={**os.environ, 'LC_ALL': 'C'})
    except subprocess.TimeoutExpired as exc:
        raise OSError('the sound server did not answer') from exc
    if done.returncode != 0:
        raise OSError(f'no audio device: {(done.stderr or "").strip()[:120] or done.returncode}')
    return done.stdout


def _percent(text: str) -> int:
    found = PERCENT.search(text)
    if not found:
        raise OSError('the sound server gave no volume')
    return int(found.group(1))


def read_audio(run=pactl) -> dict:
    """Default speaker volume/mute and default microphone mute; raises OSError when unavailable."""
    volume = _percent(run('get-sink-volume', SINK))
    speaker_muted = 'yes' in run('get-sink-mute', SINK)
    try:
        mic_muted = 'yes' in run('get-source-mute', SOURCE)
    except OSError:  # no microphone: the speaker and the mixer still work
        mic_muted = False
    return {'volume': volume, 'speaker_muted': speaker_muted, 'mic_muted': mic_muted}


def sink_inputs(run=pactl) -> list[dict]:
    """The programs that have a sound stream: {'index', 'name', 'binary', 'active', 'level', 'muted'}."""
    found = []
    for item in json.loads(run('--format=json', 'list', 'sink-inputs') or '[]'):
        properties = item.get('properties', {})
        volumes = [_percent(channel['value_percent']) for channel in item.get('volume', {}).values()]
        binary = properties.get('application.process.binary') or properties.get('application.name') or ''
        found.append({'index': item['index'], 'binary': plain(binary), 'name': properties.get('application.name', binary),
                      'active': not item.get('corked', False), 'level': max(volumes, default=0),
                      'muted': bool(item.get('mute'))})
    return found


def _app_streams(app: str, run) -> list[dict]:
    wanted = plain(app)
    return [item for item in sink_inputs(run) if wanted in (item['binary'], plain(item['name']))]


def control_audio(target: str, operation: str = 'toggle', value: int | None = None, step: int = 5, run=pactl) -> None:
    """Mute, unmute, toggle or set the volume of the speakers, the microphone or one program's sound."""
    from pc_state import APP_TARGET, check_audio
    check_audio({'target': target, 'op': operation, **({'value': value} if value is not None else {}), 'step': step})
    app = APP_TARGET.fullmatch(target)
    if app:
        streams = _app_streams(app.group(1), run)
        if not streams:
            raise OSError(f'{app.group(1)} is not playing sound right now')
        if operation == 'toggle':  # one decision for every stream of the program, so a mixed state converges
            operation = 'unmute' if all(item['muted'] for item in streams) else 'mute'
        for item in streams:
            _apply(run, 'sink-input', str(item['index']), operation, value, step, item['level'])
        return
    if target == 'mic':
        try:
            current = _percent(run('get-source-volume', SOURCE))
        except OSError as exc:
            raise OSError('no microphone is connected') from exc
        _apply(run, 'source', SOURCE, operation, value, step, current)
        return
    _apply(run, 'sink', SINK, operation, value, step, _percent(run('get-sink-volume', SINK)))


def _apply(run, kind: str, ident: str, operation: str, value, step: int, current: int) -> None:
    if operation in ('toggle', 'mute', 'unmute'):
        run(f'set-{kind}-mute', ident, {'toggle': 'toggle', 'mute': '1', 'unmute': '0'}[operation])
        return
    target = value if operation == 'volume' else current + (step if operation == 'up' else -step)
    target = max(0, min(100, target))
    if operation == 'up':  # a sink can stand above 100 (over-amplification): up must not bring it down
        target = max(current, target)
    run(f'set-{kind}-volume', ident, f'{target}%')


def read_mixer(pinned: list | None = None, mic: bool = True, run=pactl) -> list[dict]:
    """The default speaker, up to three programs and the microphone. Raises OSError without audio."""
    import cockpit
    from pc_state import APP_TARGET
    speaker = _percent(run('get-sink-volume', SINK))
    apps = {}
    for item in sink_inputs(run):
        key = item['binary']
        if not key or key in apps or not APP_TARGET.fullmatch('app:' + key) or len(key) + 4 > cockpit.MAX_ID:
            continue
        apps[key] = {'id': 'app:' + key, 'name': cockpit.app_title(key), 'active': item['active'], 'level': item['level'],
                     'muted': item['muted']}
    if pinned:
        chosen = [apps[plain(name)] for name in pinned[:cockpit.MAX_APPS] if plain(name) in apps]
    else:
        chosen = sorted(sorted(apps.values(), key=lambda app: (not app['active'], app['name'].lower()))[:cockpit.MAX_APPS],
                        key=lambda app: app['name'].lower())
    faders = [{'id': 'speaker', 'name': 'Master', 'level': speaker, 'muted': 'yes' in run('get-sink-mute', SINK),
               'color': cockpit.GREEN}]
    faders += [{'id': app['id'], 'name': app['name'], 'level': app['level'], 'muted': app['muted'],
                'color': cockpit.APP_COLORS[index]} for index, app in enumerate(chosen)]
    if mic:
        try:
            faders.append({'id': 'mic', 'name': 'Mic', 'level': _percent(run('get-source-volume', SOURCE)),
                           'muted': 'yes' in run('get-source-mute', SOURCE), 'mic': True, 'color': '#4DD0E1'})
        except OSError:  # no microphone: the mixer shows the speaker and the programs only
            pass
    return faders
