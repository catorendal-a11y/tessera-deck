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
        self.assertEqual(names, ['Meetings', 'Coding', 'Media', 'Browser'])

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
