"""Live PC state for the deck: speaker/microphone mute, volume and the current media session.

A background thread polls Windows (Core Audio via pycaw, media sessions via WinRT) and exposes
the result as label variables ($(pc:track) ...) and boolean flags that toggle buttons follow.
Both readers are injectable so the logic can be tested without audio hardware.
"""
from __future__ import annotations

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


def set_mute(target: str, operation: str = 'toggle') -> None:
    """Mute, unmute or toggle the default speaker or microphone."""
    if target not in ('speaker', 'mic') or operation not in ('toggle', 'mute', 'unmute'):
        raise ValueError(f'Unknown audio command: {target} {operation}')

    def apply(ends):
        endpoint = ends[target]
        muted = (not endpoint.GetMute()) if operation == 'toggle' else operation == 'mute'
        endpoint.SetMute(int(muted), None)

    _with_audio(apply)


class MediaReader:
    """Reads the current Windows media session (Spotify, browsers, players ...)."""

    def __init__(self):
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
