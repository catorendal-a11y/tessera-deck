"""The page templates in action_packs.json are real pages: they validate and fit the deck."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import tessera_app
import tesserad as deck

CATALOG = json.loads((Path(__file__).resolve().parents[1] / 'host/action_packs.json').read_text(encoding='utf-8'))


class PageTemplateTests(unittest.TestCase):
    def test_the_catalog_loads_with_its_page_templates(self):
        tessera_app.action_pack_catalog.cache_clear()
        names = [template['name'] for template in tessera_app.action_pack_catalog()['page_templates']]
        self.assertEqual(names, ['Meetings', 'Coding', 'Media', 'Browser', 'OBS', 'Farming Simulator'])

    def test_the_obs_page_uses_commands_and_names_the_obs_plugin_has(self):
        source = (Path(__file__).resolve().parents[1] / 'plugins/obs/main.py').read_text(encoding='utf-8')
        template = next(item for item in CATALOG['page_templates'] if item['name'] == 'OBS')
        steps = [step for key in template['page'] for step in key['actions'] if step['type'] == 'plugin']
        self.assertEqual([step['command'] for step in steps], ['record', 'stream', 'pause', 'replay', 'virtualcam', 'transition'])
        for step in steps:
            self.assertEqual(step['plugin'], 'obs')
            self.assertIn(f"'{step['command']}'", source.split('def run(', 1)[1], 'a command run() handles')
        status = {key['label']: key['status'] for key in template['page'] if 'status' in key}
        self.assertEqual({label: item['var'] for label, item in status.items()},
                         {'Record': 'obs.recording', 'Stream': 'obs.streaming', 'Pause': 'obs.paused'})
        self.assertEqual(status['Record']['colors'], {'ON': '#FF7070'})
        self.assertEqual(status['Stream']['colors'], {'ON': '#FF7070'})
        labels = [key['label'] for key in template['page']]
        for name in [item['var'] for item in status.values()] + ['obs.scene']:
            self.assertIn(f'$(var:{name})', source, 'a name the plugin sets')
        self.assertIn('$(var:obs.scene)', labels)
        self.assertIn('More → Plugins', template['description'])

    def test_power_keys_hold_to_confirm_and_sleep_does_not_hibernate(self):
        tessera_app.action_pack_catalog.cache_clear()
        packs = {pack['name']: pack for pack in tessera_app.action_pack_catalog()['packs']}
        for name in ('Shut down', 'Restart', 'Sleep', 'Sign out'):
            self.assertIs(packs[name]['confirm'], True, name)
        command = packs['Sleep']['actions'][0]['command']
        self.assertIn("SetSuspendState('Suspend', $false, $false)", command)
        self.assertNotIn('powrprof', command)  # rundll32 powrprof.dll,SetSuspendState hibernates when hibernation is on
        for name, keys in (('Game Bar', 'win+g'), ('New folder', 'ctrl+shift+n'), ('Rename', 'f2'),
                           ('New window', 'ctrl+n'), ('Private window', 'ctrl+shift+n'), ('Private (Firefox)', 'ctrl+shift+p')):
            self.assertEqual(packs[name]['actions'], [{'type': 'hotkey', 'keys': keys}], name)
        self.assertEqual(packs['System info']['actions'], [{'type': 'open', 'target': 'msinfo32.exe'}])

    def test_every_template_is_a_valid_page_with_unique_keys_and_a_back_key(self):
        for template in CATALOG['page_templates']:
            with self.subTest(template['name']):
                ids = [key['id'] for key in template['page']]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertTrue(all(1 <= number <= 18 for number in ids))
                self.assertIn(17, ids, 'a page opened from a folder needs its Back key')
                self.assertTrue(all(len(key['label']) <= 24 for key in template['page']))
                config = {'default_profile': 'p', 'profiles': {'p': {'match': [], 'pages': {'page': template['page']}}}}
                deck.validate_config(config)

    def test_a_template_with_a_broken_key_is_refused_by_the_loader(self):
        broken = json.loads(json.dumps(CATALOG))
        broken['page_templates'][0]['page'][0]['actions'] = [{'type': 'hotkey', 'keys': 'ctrl+nonsense'}]
        original = tessera_app.json.loads
        try:
            tessera_app.action_pack_catalog.cache_clear()
            tessera_app.json.loads = lambda text, *a, **k: broken
            with self.assertRaises(ValueError):
                tessera_app.action_pack_catalog()
        finally:
            tessera_app.json.loads = original
            tessera_app.action_pack_catalog.cache_clear()


if __name__ == '__main__':
    unittest.main()
