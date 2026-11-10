"""Wide keys: a key two or three slots wide can show the music that plays or a timer's countdown."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import tesserad as deck
from host_support import HostCase

CONFIG = json.loads((Path(__file__).resolve().parents[1] / 'host/profiles.default.json').read_text(encoding='utf-8'))


def page(*buttons):
    config = copy.deepcopy(CONFIG)
    config['profiles']['main']['pages']['wide'] = [dict({'label': 'K', 'icon': 'ok', 'color': '#35D07F', 'actions': []}, **b) for b in buttons]
    return config


class ValidationTests(unittest.TestCase):
    def test_a_wide_key_needs_free_slots_to_its_right_on_the_same_row(self):
        deck.validate_config(page({'id': 1, 'span': 3, 'live': 'media'}, {'id': 4}))
        for bad in (page({'id': 1, 'span': 3}, {'id': 3}),            # a key sits in a covered slot
                    page({'id': 5, 'span': 3}),                        # runs off the end of the row
                    page({'id': 6, 'span': 2}),
                    page({'id': 1, 'span': 4}), page({'id': 1, 'span': 'wide'}),
                    page({'id': 1, 'span': 1, 'live': 'media'}),      # live needs room
                    page({'id': 1, 'span': 2, 'live': 'weather'}), page({'id': 1, 'span': 2, 'live': 'timer:bad name'})):
            with self.assertRaises(ValueError, msg=str(bad['profiles']['main']['pages']['wide'])):
                deck.validate_config(bad)

    def test_a_timer_key_is_valid(self):
        deck.validate_config(page({'id': 1, 'span': 2, 'live': 'timer:pomodoro'}))


class ContentTests(HostCase):
    def test_a_media_key_shows_title_artist_and_progress(self):
        daemon = self.daemon(page({'id': 1, 'span': 3, 'live': 'media', 'icon': 'play'}))
        daemon.profile, daemon.page = 'main', 'wide'
        daemon.pc._values.update(title='Midnight City', artist='M83', status='PLAYING', position=61.0, duration=244.0)
        entry = daemon.current_buttons()[0]
        self.assertEqual((entry['span'], entry['label'], entry['sub'], entry['progress']), (3, 'Midnight City', 'M83', 25))
        daemon.pc._values.update(title='', artist='', status='', duration=0.0)
        entry = daemon.current_buttons()[0]
        self.assertEqual(entry['label'], 'No music')
        self.assertNotIn('progress', entry)

    def test_a_timer_key_shows_the_time_left_as_a_ring(self):
        daemon = self.daemon(page({'id': 1, 'span': 2, 'live': 'timer:pomodoro'}))
        daemon.profile, daemon.page = 'main', 'wide'
        daemon.live.apply_timer({'type': 'timer', 'name': 'pomodoro', 'op': 'start', 'seconds': 100})
        entry = daemon.current_buttons()[0]
        self.assertTrue(entry['ring'])
        self.assertGreaterEqual(entry['progress'], 99)
        self.assertEqual(entry['label'], '01:40')
        self.assertIn('pomodoro', entry['sub'])

    def test_an_ordinary_key_gets_none_of_the_wide_fields(self):
        daemon = self.daemon(page({'id': 1}))
        daemon.profile, daemon.page = 'main', 'wide'
        entry = daemon.current_buttons()[0]
        self.assertFalse({'span', 'sub', 'progress', 'ring'} & set(entry))


if __name__ == '__main__':
    unittest.main()
