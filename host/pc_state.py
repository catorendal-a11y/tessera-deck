"""Live PC state for the deck: speaker/microphone mute, volume and the current media session.

A background thread polls the system's sound and media (platform_windows/audio.py and media.py) and exposes the result as label variables ($(pc:track) ...) and boolean flags that toggle buttons
follow. Both readers are injectable so the logic can be tested without audio hardware.
"""
from __future__ import annotations

import re
import threading
from typing import Callable

from program_name import SUFFIX

POLL_SECONDS = 1.0
FLAG_SOURCES = ('speaker_muted', 'mic_muted', 'media_playing', 'media_shuffle', 'media_repeat')
EMPTY = {'volume': None, 'speaker_muted': False, 'mic_muted': False,
         'title': '', 'artist': '', 'status': '', 'position': 0.0, 'duration': 0.0, 'shuffle': None, 'repeat': ''}


AUDIO_OPERATIONS = ('toggle', 'mute', 'unmute', 'volume', 'up', 'down')
APP_TARGET = re.compile(rf'app:([A-Za-z0-9_.-]{{1,64}}{SUFFIX})', re.IGNORECASE)  # a program name ends in .exe


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


MEDIA_OPERATIONS = ('shuffle', 'repeat')


def check_media(action: dict) -> None:
    if action.get('op') not in MEDIA_OPERATIONS:
        raise ValueError(f'media: op must be one of {", ".join(MEDIA_OPERATIONS)}')


class PcState:
    def __init__(self, audio: Callable[[], dict] | None = None, media: Callable[[], dict] | None = None,
                 interval: float = POLL_SECONDS):
        import system_audio  # the readers of this system, unless the caller brings its own
        self._audio = system_audio.read_audio if audio is None else audio
        self._media = system_audio.MediaReader() if media is None else media
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
            except Exception as exc:  # a changed pycaw/winrt API must not end the polling thread without a word
                errors.append(str(exc) or type(exc).__name__)
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
        if source == 'media_shuffle':
            return values['shuffle'] is True
        if source == 'media_repeat':
            return values['repeat'] in ('track', 'list')
        return bool(values.get(source, False))

    def variables(self) -> dict[str, str]:
        values = self.snapshot()
        volume = values['volume']
        track = ' - '.join(part for part in (values['artist'], values['title']) if part)
        return {'pc:volume': '' if volume is None else f'{volume}%',
                'pc:speaker': 'MUTED' if values['speaker_muted'] else 'ON',
                'pc:mic': 'MUTED' if values['mic_muted'] else 'LIVE',
                'pc:track': values['title'] or 'No music', 'pc:artist': values['artist'], 'pc:media': track,
                'pc:playing': values['status'],
                'pc:shuffle': '' if values['shuffle'] is None else 'ON' if values['shuffle'] else 'OFF',
                'pc:repeat': {'none': 'OFF', 'list': 'ALL', 'track': 'ONE'}.get(values['repeat'], '')}
