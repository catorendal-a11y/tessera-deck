"""Editor test mode (dry run), shared substitution and the editor's city search; nothing is executed."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import ambient
import iconify
from action_preview import preview
from substitution import expand_environment, substitute
from tessera_app import Editor


def nowhere(target):
    return None


class SubstitutionTests(unittest.TestCase):
    def test_plain_shell_and_url_modes(self):
        variables = {'var:name': 'a b&c', 'stat:cpu': '42%'}
        self.assertEqual(substitute('Hi $(var:name) $(stat:cpu)', variables), 'Hi a b&c 42%')
        self.assertEqual(substitute('?q=$(var:name)', variables, 'url'), '?q=a%20b%26c')
        with self.assertRaises(ValueError):
            substitute('echo $(var:name)', variables, 'shell')
        self.assertEqual(substitute('echo $(stat:cpu)', {'stat:cpu': '42'}, 'shell'), 'echo 42')
        self.assertEqual(substitute('x$(var:unset)y', {}), 'xy')

    def test_environment_references(self):
        self.assertEqual(expand_environment('Bearer $(env:TOKEN)/$(env:MISSING)', {'TOKEN': 't'}), 'Bearer t/')


class PreviewTests(unittest.TestCase):
    def run_preview(self, actions, variables=None, **kwargs):
        return preview(actions, variables or {}, locator=nowhere, **kwargs)

    def test_a_good_multi_action_is_described_step_by_step_and_nothing_runs(self):
        actions = [{'type': 'hotkey', 'keys': 'ctrl+shift+m'}, {'type': 'delay', 'ms': 1500},
                   {'type': 'text', 'text': 'Hello $(var:who)'}, {'type': 'page', 'page': 'tools'},
                   {'type': 'counter', 'name': 'laps', 'op': 'inc', 'step': 2},
                   {'type': 'timer', 'name': 'tea', 'op': 'start', 'seconds': 180, 'notify': 'Tea!'},
                   {'type': 'audio', 'target': 'mic', 'op': 'toggle'}]
        result = self.run_preview(actions, {'var:who': 'Ada'})
        self.assertTrue(result['ok'])
        self.assertFalse(result['executed'])
        self.assertEqual(result['wait_seconds'], 1.5)
        texts = [step['text'] for step in result['steps']]
        self.assertEqual(texts[0], 'Press ctrl+shift+m')
        self.assertEqual(texts[1], 'Wait 1.5 s')
        self.assertEqual(texts[2], 'Type "Hello Ada"')
        self.assertIn('add 2 to laps', texts[4])
        self.assertIn('Timer tea: start for 180 s, notify "Tea!"', texts[5])
        self.assertEqual(texts[6], 'Toggle the mic')

    def test_problems_are_reported_per_step_without_stopping_the_preview(self):
        missing_dir = str(Path(tempfile.gettempdir()) / 'tessera-no-such-folder' / 'tool.exe')
        actions = [{'type': 'hotkey', 'keys': 'not-a-key'}, {'type': 'open', 'target': missing_dir},
                   {'type': 'shell', 'command': 'echo $(var:evil)'}, {'type': 'http', 'url': 'ftp://example.com'},
                   {'type': 'bogus'}, {'type': 'text', 'text': 'still described'}]
        result = self.run_preview(actions, {'var:evil': 'a & b'})
        self.assertFalse(result['ok'])
        self.assertEqual([step['ok'] for step in result['steps']], [False, False, False, False, False, True])
        self.assertIn('not found', result['steps'][1]['text'])
        self.assertIn('not allowed in a shell command', result['steps'][2]['text'])
        self.assertIn('http://', result['steps'][3]['text'])

    def test_programs_that_moved_are_reported_as_found_elsewhere(self):
        result = preview([{'type': 'open', 'target': r'C:\Gone\app.exe'}], {},
                         locator=lambda target: r'D:\Apps\app.exe')
        self.assertTrue(result['ok'])
        self.assertIn(r'D:\Apps\app.exe', result['steps'][0]['text'])
        self.assertIn('different place', result['steps'][0]['text'])

    def test_web_links_and_settings_pages_need_no_lookup(self):
        result = self.run_preview([{'type': 'open', 'target': 'https://example.com'},
                                   {'type': 'open', 'target': 'ms-settings:sound'}])
        self.assertTrue(result['ok'])

    def test_http_credentials_come_from_the_environment_and_must_exist(self):
        action = {'type': 'http', 'url': 'https://example.com/x', 'method': 'POST',
                  'headers': {'Authorization': 'Bearer $(env:TESSERA_TOKEN)'}, 'body': '{}'}
        missing = self.run_preview([action], environment={})
        self.assertFalse(missing['ok'])
        self.assertIn('TESSERA_TOKEN is not set', missing['steps'][0]['text'])
        present = self.run_preview([action], environment={'TESSERA_TOKEN': 'x'})
        self.assertTrue(present['ok'])
        self.assertIn('from the environment', present['steps'][0]['text'])
        self.assertNotIn('Bearer', present['steps'][0]['text'])

    def test_malformed_actions_do_not_crash_the_preview(self):
        result = self.run_preview([{'type': 'hotkey'}, {'type': 'page'}, {'type': 'timer'}, {}])
        self.assertFalse(result['ok'])
        self.assertEqual(len(result['steps']), 4)


class EditorCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / 'profiles.json'
        path.write_text(json.dumps({'default_profile': 'Main', 'profiles': {'Main': {'match': [], 'pages': {
            'First': []}}}}))
        self.editor = Editor(path, dashboard=lambda: {'running': True, 'device': {},
                                                       'variables': {'var:who': 'Grace'}})

    def test_dry_run_uses_the_panels_current_variables_and_validates_the_request(self):
        result = self.editor.command('dryrun', {'actions': [{'type': 'text', 'text': 'Hi $(var:who)'}],
                                                'hold_actions': [{'type': 'hotkey', 'keys': 'ctrl+c'}]})
        self.assertEqual(result['actions']['steps'][0]['text'], 'Type "Hi Grace"')
        self.assertEqual(result['hold_actions']['steps'][0]['text'], 'Press ctrl+c')
        for bad in ({}, {'actions': 'x'}, {'actions': ['x']}, {'actions': [{'type': 'delay'}] * 51}):
            with self.assertRaises(ValueError):
                self.editor.command('dryrun', bad)

    def test_city_search_goes_through_the_editor_and_reports_an_offline_service_plainly(self):
        place = [{'name': 'Oslo', 'region': 'Oslo', 'country': 'Norway', 'latitude': 59.9, 'longitude': 10.7}]
        with patch.object(ambient, 'search_places', return_value=place) as search:
            self.assertEqual(self.editor.command('weather-search', {'query': 'Oslo'}), {'places': place})
        search.assert_called_once_with('Oslo')
        with patch.object(ambient, 'search_places', side_effect=OSError('offline')):
            with self.assertRaises(ValueError) as raised:
                self.editor.command('weather-search', {'query': 'Oslo'})
        self.assertIn('internet connection', str(raised.exception))


class FakeIconReply:
    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, limit):
        return self.body[:limit]


class IconifyTests(unittest.TestCase):
    def answering(self, body, seen=None):
        def opener(request, timeout):
            if seen is not None:
                seen.append(request.full_url)
            return FakeIconReply(body)
        return opener

    def test_search_keeps_only_well_formed_icon_ids(self):
        body = json.dumps({'icons': ['mdi:home', 'lucide:house', 'bad id', 'x:../etc', 5, 'mdi:Home']})
        seen = []
        self.assertEqual(iconify.search('home', self.answering(body, seen)), ['mdi:home', 'lucide:house'])
        self.assertTrue(seen[0].startswith('https://api.iconify.design/search?'))
        for query in ('', 'a', 'x' * 41):
            with self.assertRaises(ValueError):
                iconify.search(query, self.answering('{}'))
        for broken in ('not json', '[]', '{"icons": "no"}'):
            with self.assertRaises(ValueError):
                iconify.search('home', self.answering(broken))

    def test_svg_is_fetched_for_one_icon_in_the_chosen_color_and_must_be_plain(self):
        plain = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0h24v24H0z" fill="#FF0000"/></svg>'
        seen = []
        self.assertEqual(iconify.svg('mdi:home', '#FF0000', self.answering(plain, seen)), plain)
        self.assertIn('/mdi/home.svg?', seen[0])
        self.assertIn('color=%23FF0000', seen[0])
        for hostile in ('<svg><script>alert(1)</script></svg>', '<svg onload="x()"></svg>',
                        '<svg><image href="http://evil/x.png"/></svg>', '<svg><use xlink:href="#a"/></svg>',
                        '<html></html>', '<svg>' + 'x' * (iconify.MAX_SVG_BYTES + 10) + '</svg>'):
            with self.assertRaises(ValueError, msg=hostile[:30]):
                iconify.svg('mdi:home', '#FFFFFF', self.answering(hostile))

    def test_icon_names_and_colors_are_validated_before_any_request(self):
        seen = []
        for icon_id, color in (('mdi/home', '#FFFFFF'), ('../x:y', '#FFFFFF'), ('mdi:home', 'red'),
                               ('mdi:home', '#FFF'), ('', '#FFFFFF')):
            with self.assertRaises(ValueError):
                iconify.svg(icon_id, color, self.answering('<svg></svg>', seen))
        self.assertEqual(seen, [])

    def test_the_editor_proxies_both_commands_and_explains_an_offline_service(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'profiles.json'
            path.write_text(json.dumps({'default_profile': 'Main', 'profiles': {'Main': {'match': [], 'pages': {
                'First': []}}}}))
            editor = Editor(path, dashboard=lambda: {'running': False, 'device': {}})
            with patch.object(iconify, 'search', return_value=['mdi:home']):
                self.assertEqual(editor.command('iconify-search', {'query': 'home'}), {'icons': ['mdi:home']})
            with patch.object(iconify, 'svg', return_value='<svg></svg>') as svg:
                self.assertEqual(editor.command('iconify-svg', {'id': 'mdi:home', 'color': '#00FF00'}),
                                 {'svg': '<svg></svg>'})
            svg.assert_called_once_with('mdi:home', '#00FF00')
            with patch.object(iconify, 'search', side_effect=OSError('offline')):
                with self.assertRaises(ValueError) as raised:
                    editor.command('iconify-search', {'query': 'home'})
            self.assertIn('internet connection', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
