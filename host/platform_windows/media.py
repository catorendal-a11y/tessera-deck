"""The media session on Windows (WinRT System Media Transport Controls): reading it, and changing shuffle and repeat."""
from __future__ import annotations

from datetime import datetime, timezone

from pc_state import check_media


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
            return {'title': '', 'artist': '', 'status': '', 'position': 0.0, 'duration': 0.0, 'shuffle': None, 'repeat': ''}
        properties = await session.try_get_media_properties_async()
        info = session.get_playback_info()
        status = info.playback_status
        position, duration = 0.0, 0.0
        try:  # not every player reports a timeline; the bar is then left out
            timeline = session.get_timeline_properties()
            start = timeline.start_time.total_seconds()
            position, duration = timeline.position.total_seconds() - start, timeline.end_time.total_seconds() - start
            if int(status) == 4:  # the position is only true at last_updated_time; a playing track has moved on since
                updated = timeline.last_updated_time
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                position += max(0.0, (datetime.now(timezone.utc) - updated).total_seconds())
                if duration > 0:
                    position = min(position, duration)
        except (AttributeError, OSError, ValueError):
            pass
        shuffle, repeat = None, ''
        try:  # a failure here must not cost the title and the playing state
            shuffle = info.is_shuffle_active  # None when the player does not report it
        except (AttributeError, OSError, ValueError, TypeError):
            shuffle = None
        try:  # reading the mode needs winrt-Windows.Media for its enum; without it only repeat is lost
            if info.auto_repeat_mode is not None:
                repeat = REPEAT_NAMES.get(int(info.auto_repeat_mode), '')
        except (AttributeError, OSError, ValueError, TypeError, ImportError):
            repeat = ''
        return {'title': properties.title or '', 'artist': properties.artist or '',
                'status': {4: 'PLAYING', 5: 'PAUSED', 3: 'STOPPED'}.get(int(status), ''),
                'position': position, 'duration': duration, 'shuffle': shuffle, 'repeat': repeat}


REPEAT_NAMES = {0: 'none', 1: 'track', 2: 'list'}  # MediaPlaybackAutoRepeatMode


NEXT_REPEAT = {0: 2, 2: 1, 1: 0}  # off, all, one, off


async def _change_media_option(session, operation: str) -> bool:
    """Toggle shuffle or cycle repeat on a media session; False when the player cannot do it."""
    info = session.get_playback_info()
    controls = info.controls
    if operation == 'shuffle':
        if info.is_shuffle_active is None or not controls.is_shuffle_enabled:
            return False
        return bool(await session.try_change_shuffle_active_async(not info.is_shuffle_active))
    try:
        mode = info.auto_repeat_mode
    except ImportError as exc:  # the value's enum lives in winrt-Windows.Media
        raise OSError('Repeat needs the winrt-Windows.Media package. Run Tessera.cmd once to install it.') from exc
    if mode is None or not controls.is_repeat_enabled:
        return False
    # the enum class comes from the value itself, so nothing more is imported here
    return bool(await session.try_change_auto_repeat_mode_async(type(mode)(NEXT_REPEAT[int(mode)])))


def control_media(operation: str) -> None:
    """Toggle shuffle or cycle repeat in the current media session. A player without it is left alone, and the
    OSError says so: otherwise the key would report success for a press that changed nothing."""
    check_media({'op': operation})
    try:
        import asyncio
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
    except ImportError as exc:
        raise OSError(f'media control is not installed: {exc}') from exc

    async def work():
        session = (await Manager.request_async()).get_current_session()
        if session is None:
            raise OSError('No player is open in the Windows media controls')
        if not await _change_media_option(session, operation):
            raise OSError(f'This player does not offer {operation}')

    asyncio.run(work())
