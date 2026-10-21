"""Live PC state for the deck: speaker/microphone mute, volume and the current media session.

A background thread polls Windows (Core Audio via pycaw, media sessions via WinRT) and exposes
the result as label variables ($(pc:track) ...) and boolean flags that toggle buttons follow.
Both readers are injectable so the logic can be tested without audio hardware.
"""
from __future__ import annotations

import re
import threading
from typing import Callable

POLL_SECONDS = 1.0
FLAG_SOURCES = ('speaker_muted', 'mic_muted', 'media_playing')
EMPTY = {'volume': None, 'speaker_muted': False, 'mic_muted': False,
         'title': '', 'artist': '', 'status': ''}


def _endpoints() -> dict:
    """Default speaker and microphone endpoint volume interfaces (call between CoInitialize/Uninitialize)."""
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.api.endpointvolume import IAudioEndpointVolume
        from pycaw.constants import EDataFlow, ERole
        from pycaw.pycaw import AudioUtilities
    except ImportError as exc:
        raise OSError(f'audio control is not installed: {exc}') from exc
    enumerator = AudioUtilities.GetDeviceEnumerator()

    def endpoint(flow):
        device = enumerator.GetDefaultAudioEndpoint(flow.value, ERole.eMultimedia.value)
        return device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None).QueryInterface(IAudioEndpointVolume)

    return {'speaker': endpoint(EDataFlow.eRender), 'mic': endpoint(EDataFlow.eCapture)}


def _with_audio(work):
    try:
        import comtypes
    except ImportError as exc:
        raise OSError(f'audio control is not installed: {exc}') from exc
    comtypes.CoInitialize()
    try:
        return work(_endpoints())
    except comtypes.COMError as exc:
        raise OSError(f'no audio device: {exc}') from exc
    finally:
        comtypes.CoUninitialize()


def read_audio() -> dict:
    """Default speaker volume/mute and default microphone mute; raises OSError when unavailable."""
    return _with_audio(lambda ends: {
        'volume': round(ends['speaker'].GetMasterVolumeLevelScalar() * 100),
        'speaker_muted': bool(ends['speaker'].GetMute()), 'mic_muted': bool(ends['mic'].GetMute())})


AUDIO_OPERATIONS = ('toggle', 'mute', 'unmute', 'volume', 'up', 'down')
APP_TARGET = re.compile(r'app:([A-Za-z0-9_.-]{1,64}\.exe)', re.IGNORECASE)


def check_audio(action: dict) -> None:
    """Validate an `audio` action: target speaker, mic or app:NAME.exe and what to do with it."""
    target = action.get('target')
    if not isinstance(target, str) or (target not in ('speaker', 'mic') and not APP_TARGET.fullmatch(target)):
        raise ValueError('audio: target is speaker, mic or app:NAME.exe')
    if action.get('op', 'toggle') not in AUDIO_OPERATIONS:
        raise ValueError(f'audio: op must be one of {", ".join(AUDIO_OPERATIONS)}')
    for key, low, high in (('value', 0, 100), ('step', 1, 50)):
        if key in action and (type(action[key]) is not int or not low <= action[key] <= high):
            raise ValueError(f'audio: {key} must be a whole number from {low} to {high}')
    if action.get('op') == 'volume' and 'value' not in action:
        raise ValueError('audio: volume needs a value from 0 to 100')


class _Control:
    """The four calls the audio operations need, for a device endpoint or one app's audio session."""

    def __init__(self, get_mute, set_mute, get_volume, set_volume):
        self.get_mute, self.set_mute, self.get_volume, self.set_volume = get_mute, set_mute, get_volume, set_volume


def apply_operation(control: _Control, operation: str, value: int | None = None, step: int = 5) -> None:
    if operation in ('toggle', 'mute', 'unmute'):
        muted = (not control.get_mute()) if operation == 'toggle' else operation == 'mute'
        control.set_mute(int(muted), None)
        return
    current = round(control.get_volume() * 100)
    target = value if operation == 'volume' else current + (step if operation == 'up' else -step)
    control.set_volume(max(0, min(100, target)) / 100, None)


def _app_controls(name: str) -> list[_Control]:
    from pycaw.pycaw import AudioUtilities
    controls = []
    for session in AudioUtilities.GetAllSessions():
        process = session.Process
        if process is not None and process.name().casefold() == name.casefold():
            volume = session.SimpleAudioVolume
            controls.append(_Control(volume.GetMute, volume.SetMute, volume.GetMasterVolume, volume.SetMasterVolume))
    return controls


def control_audio(target: str, operation: str = 'toggle', value: int | None = None, step: int = 5) -> None:
    """Mute, unmute, toggle or set the volume of the speakers, the microphone or one program's sound."""
    check_audio({'target': target, 'op': operation, **({'value': value} if value is not None else {}), 'step': step})
    app = APP_TARGET.fullmatch(target)
    if app:
        try:
            import comtypes
        except ImportError as exc:
            raise OSError(f'audio control is not installed: {exc}') from exc
        comtypes.CoInitialize()
        try:
            controls = _app_controls(app.group(1))
            if not controls:
                raise OSError(f'{app.group(1)} is not playing sound right now')
            for control in controls:
                apply_operation(control, operation, value, step)
        finally:
            comtypes.CoUninitialize()
        return

    def apply(ends):
        endpoint = ends[target]
        apply_operation(_Control(endpoint.GetMute, endpoint.SetMute, endpoint.GetMasterVolumeLevelScalar,
                                 endpoint.SetMasterVolumeLevelScalar), operation, value, step)

    _with_audio(apply)


class MediaReader:
    """Reads the current Windows media session (Spotify, browsers, players ...)."""

    def __init__(self):
        self._loop = None
        self._manager = None

    def close(self) -> None:
        if self._loop is not None:
            self._loop.close()
            self._loop = None
        self._manager = None

    def __call__(self) -> dict:
        try:
            import asyncio
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
        except ImportError as exc:
            raise OSError(f'media control is not installed: {exc}') from exc
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(self._read(Manager))

    async def _read(self, manager_type) -> dict:
        if self._manager is None:
            self._manager = await manager_type.request_async()
        session = self._manager.get_current_session()
        if session is None:
            return {'title': '', 'artist': '', 'status': ''}
        properties = await session.try_get_media_properties_async()
        status = session.get_playback_info().playback_status
        return {'title': properties.title or '', 'artist': properties.artist or '',
                'status': {4: 'PLAYING', 5: 'PAUSED', 3: 'STOPPED'}.get(int(status), '')}


class PcState:
    def __init__(self, audio: Callable[[], dict] = read_audio, media: Callable[[], dict] | None = None,
                 interval: float = POLL_SECONDS):
        self._audio = audio
        self._media = media or MediaReader()
        self._interval = interval
        self._lock = threading.Lock()
        self._values = dict(EMPTY)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error = ''

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name='pc-state', daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)
        close = getattr(self._media, 'close', None)
        if close:
            close()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.poll()
            self._stop.wait(self._interval)

    def poll(self) -> None:
        """One sampling round; a failing source keeps its last value and records the error."""
        errors = []
        for reader in (self._audio, self._media):
            try:
                reading = reader()
            except (OSError, RuntimeError, ValueError) as exc:
                errors.append(str(exc))
                continue
            with self._lock:
                self._values.update(reading)
        self.error = '; '.join(errors)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._values)

    def flag(self, source: str) -> bool:
        values = self.snapshot()
        if source == 'media_playing':
            return values['status'] == 'PLAYING'
        return bool(values.get(source, False))

    def variables(self) -> dict[str, str]:
        values = self.snapshot()
        volume = values['volume']
        track = ' - '.join(part for part in (values['artist'], values['title']) if part)
        return {'pc:volume': '' if volume is None else f'{volume}%',
                'pc:speaker': 'MUTED' if values['speaker_muted'] else 'ON',
                'pc:mic': 'MUTED' if values['mic_muted'] else 'LIVE',
                'pc:track': values['title'], 'pc:artist': values['artist'], 'pc:media': track,
                'pc:playing': values['status']}
