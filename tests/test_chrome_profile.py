"""The bundled Chrome screen: shown when Chrome is in front, complete and consistent."""
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck


def chrome():
    config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
    return config, config['profiles']['Chrome']


class ChromeProfileTests(unittest.TestCase):
    def test_it_is_part_of_the_defaults_and_valid(self):
        config, profile = chrome()
        deck.validate_config(config)
        self.assertEqual(profile['match'], ['chrome.exe'])
        self.assertEqual(list(profile['pages']), ['main', 'developer'])

    def test_every_key_has_a_slot_a_short_label_an_icon_and_an_action(self):
        _, profile = chrome()
        for name, keys in profile['pages'].items():
            slots = [key['id'] for key in keys]
            self.assertEqual(len(slots), len(set(slots)), name)
            self.assertTrue(all(1 <= slot <= 17 for slot in slots), name)
            for key in keys:
                with self.subTest(page=name, key=key['label']):
                    self.assertLessEqual(len(key['label'].encode()), 24)
                    self.assertTrue(key['icon'].startswith('lc:'))
                    self.assertTrue(key['actions'])

    def test_home_is_pinned_in_the_last_slot_like_the_other_profiles(self):
        _, profile = chrome()
        self.assertEqual([(key['id'], key['actions']) for key in profile['pinned']], [(18, [{'type': 'home'}])])

    def test_the_developer_page_can_be_reached_and_left(self):
        _, profile = chrome()
        self.assertTrue(any(a == {'type': 'folder', 'page': 'developer'}
                            for key in profile['pages']['main'] for a in key['actions']))
        self.assertTrue(any(a == {'type': 'back'} for key in profile['pages']['developer'] for a in key['actions']))

    def test_the_main_page_has_the_everyday_keys(self):
        _, profile = chrome()
        combos = {a.get('keys') for key in profile['pages']['main'] for a in key['actions']}
        for wanted in ('ctrl+t', 'ctrl+w', 'ctrl+shift+t', 'ctrl+tab', 'ctrl+shift+tab', 'ctrl+l', 'alt+left', 'alt+right',
                       'ctrl+r', 'ctrl+f', 'ctrl+d'):
            self.assertIn(wanted, combos)

    def test_chrome_in_front_switches_to_the_screen_and_back(self):
        daemon = deck.Daemon(types.SimpleNamespace(profiles=str(ROOT / 'host/profiles.default.json'), port='TEST',
                                                   verbose=False, no_focus=False, deck_only=True))
        daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
        shown = {'exe': 'chrome.exe', 'title': 'new tab - google chrome', 'processes': ['chrome.exe']}
        with patch.object(deck, 'foreground_context', return_value=shown):
            daemon.focus_tick()
        self.assertEqual(daemon.jobs.get_nowait(), ('profile', 'Chrome'))

    def test_the_browser_template_uses_the_same_keys_for_all_three_browsers(self):
        catalog = json.loads((ROOT / 'host/action_packs.json').read_text(encoding='utf-8'))
        template = next(item for item in catalog['templates'] if item['name'] == 'Browser')
        self.assertEqual(template['profile']['match'], ['chrome.exe', 'msedge.exe', 'firefox.exe'])
        self.assertEqual(template['profile']['pages'], chrome()[1]['pages'])


if __name__ == '__main__':
    unittest.main()
