"""The progress of the playing track keeps moving: Windows gives the position as it was at its last update time."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))

from platform_windows import media  # noqa: E402


def read(status, position, end, start=0, updated_ago=10):
    async def properties():
        return Mock(title='Song', artist='Band')
    timeline = Mock(position=timedelta(seconds=position), start_time=timedelta(seconds=start), end_time=timedelta(seconds=end),
                    last_updated_time=datetime.now(timezone.utc) - timedelta(seconds=updated_ago))
    info = Mock(playback_status=status, is_shuffle_active=None, auto_repeat_mode=None)
    session = Mock(try_get_media_properties_async=properties, get_playback_info=lambda: info, get_timeline_properties=lambda: timeline)
    reader = media.MediaReader()
    reader._manager = Mock(get_current_session=lambda: session)
    return asyncio.run(reader._read(None))


class PositionTests(unittest.TestCase):
    def test_a_playing_track_has_moved_on_since_the_last_update(self):
        self.assertAlmostEqual(read(4, 30, 200)['position'], 40, delta=1)

    def test_a_paused_track_stays_where_it_was(self):
        self.assertEqual(read(5, 30, 200)['position'], 30)

    def test_the_position_is_counted_from_the_start_time_and_never_passes_the_end(self):
        self.assertAlmostEqual(read(4, 35, 200, start=5)['position'], 40, delta=1)
        self.assertEqual(read(4, 30, 35)['position'], 35)

    def test_an_update_time_in_the_future_adds_nothing(self):
        self.assertEqual(read(4, 30, 200, updated_ago=-60)['position'], 30)


if __name__ == '__main__':
    unittest.main()
