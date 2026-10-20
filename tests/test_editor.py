"""Local editor persistence, conflicts and browser security; no USB or OS actions."""
import copy
from http.cookiejar import CookieJar
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from tessera_app import Editor, make_server


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'profiles.json'
        self.config = {'default_profile': 'Main', 'profiles': {'Main': {'match': [], 'pages': {
            'First': [{'id': 1, 'label': 'Copy', 'icon': 'ok', 'actions': [{'type': 'hotkey', 'keys': 'ctrl+c'}]}],
            'Empty': []}}}}
        self.path.write_text(json.dumps(self.config))
        self.editor = Editor(self.path, dashboard=lambda: {'running': False, 'device': {}})
        self.server = make_server(self.editor, token='test-session-only')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        h = {'Content-Type': 'application/json', 'X-Deck-Request': '1'}
        h.update(headers or {})
        request = urllib.request.Request(self.url + path, headers=h,
            data=None if data is None else json.dumps(data).encode())
        return self.client.open(request)

    def login(self):
        with self.request('/api/session', {}, {'X-Deck-Token': 'test-session-only'}) as reply:
            self.assertIn('HttpOnly', reply.headers['Set-Cookie'])
            self.assertIn('SameSite=Strict', reply.headers['Set-Cookie'])

    def test_no_unauthenticated_config_or_cross_origin_actions(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/config')
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        self.login()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/config', {}, {'Origin': 'https://unrelated.example'})
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/config', headers={'Host': 'unrelated.example'})
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

    def test_requires_custom_header_even_with_session(self):
        self.login()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/command/activate', {}, {'X-Deck-Request': ''})
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

    def test_save_preserves_multi_actions_empty_pages_and_backup(self):
        self.login()
        state = self.editor.read()
        updated = copy.deepcopy(self.config)
        b = updated['profiles']['Main']['pages']['First'][0]
        b.update(id=18, label='Moved é', color='#35D07F')
        b['actions'].append({'type': 'delay', 'ms': 500})
        b['actions'].append({'type': 'text', 'text': 'Café ñ'})
        with self.request('/api/config', dict(config=updated, revision=state['revision'])) as reply:
            result = json.load(reply)
        self.assertEqual(result['config'], updated)
        self.assertNotEqual(state['revision'], result['revision'])
        self.assertEqual(json.loads(self.path.with_name('profiles-previous.local.json').read_text()), self.config)

    def test_display_settings_round_trip_and_bad_values_are_rejected(self):
        self.login()
        state = self.editor.read()
        updated = dict(copy.deepcopy(self.config), display={'brightness': 60, 'dim_after': 300, 'dim_level': 5})
        with self.request('/api/config', dict(config=updated, revision=state['revision'])) as reply:
            result = json.load(reply)
        self.assertEqual(result['config']['display'], {'brightness': 60, 'dim_after': 300, 'dim_level': 5})
        broken = dict(updated, display={'brightness': 0})
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/config', dict(config=broken, revision=result['revision']))
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        self.assertEqual(self.editor.read()['config']['display']['brightness'], 60)

    @unittest.skipUnless(sys.platform == 'win32', 'the taskbar identity is a Windows feature')
    def test_editor_process_gets_its_own_taskbar_identity(self):
        import tessera_app
        with patch('ctypes.windll') as windll:
            tessera_app.brand_taskbar_identity()
        windll.shell32.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with('Tessera.Editor')

    def test_stale_editor_cannot_overwrite_terminal_changes(self):
        self.login()
        original = self.editor.read()
        self.path.write_text(json.dumps(dict(self.config, default_profile='Main'), indent=2))
        changed = self.path.read_bytes()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/config', original)
        self.assertEqual(error.exception.code, 409)
        error.exception.close()
        self.assertEqual(self.path.read_bytes(), changed)

    def test_invalid_action_never_changes_disk(self):
        self.login()
        original = self.editor.read()
        old = self.path.read_bytes()
        original['config']['profiles']['Main']['pages']['First'][0]['actions'] = [{'type': 'hotkey', 'keys': 'not-a-key'}]
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/config', original)
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        self.assertEqual(self.path.read_bytes(), old)

    def test_only_fixed_assets_and_no_execution_endpoint(self):
        self.login()
        with self.request('/app.js') as reply:
            self.assertIn("frame-ancestors 'none'", reply.headers['Content-Security-Policy'])
            self.assertIn('script', reply.headers['Content-Type'])
        for path in ('/../host/profiles.json', '/api/command/execute'):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(path, {} if '/api/' in path else None)
            error.exception.close()

    def test_large_icon_catalog_and_persistent_preferences(self):
        self.login()
        with self.request('/api/icons') as reply:
            catalog = json.load(reply)
        self.assertGreater(catalog['count'], 1800)
        self.assertEqual(catalog['count'], len({item['id'] for item in catalog['icons']}))
        chosen = catalog['icons'][-1]['id']
        with self.request('/api/icon-preferences', {'favorites': [chosen], 'recent': [chosen]}) as reply:
            self.assertEqual(json.load(reply)['favorites'], [chosen])
        original = self.editor.read()
        original['config']['profiles']['Main']['pages']['First'][0]['icon'] = chosen
        with self.request('/api/config', original) as reply:
            self.assertEqual(json.load(reply)['config']['profiles']['Main']['pages']['First'][0]['icon'], chosen)
        self.assertEqual(self.editor.icon_preferences()['recent'], [chosen])
        original = self.editor.read()
        original['config']['profiles']['Main']['pages']['First'][0]['icon'] = 'lc:ffff'
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/config', original)
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_bundled_action_packs_and_profile_templates_are_valid(self):
        self.login()
        with self.request('/api/action-packs') as reply:
            catalog = json.load(reply)
        self.assertEqual(catalog['version'], 1)
        self.assertGreaterEqual(len(catalog['packs']), 119)
        self.assertGreaterEqual(len(catalog['templates']), 10)
        self.assertTrue(all(pack['actions'] for pack in catalog['packs']))
        template_names = {template['name'] for template in catalog['templates']}
        self.assertTrue({'Windows control', 'GitHub Desktop', 'PowerToys',
                         'Codex', 'Claude Code', 'ZCode'} <= template_names)
        groups = {pack['group'] for pack in catalog['packs']}
        self.assertTrue({'Window management', 'PowerToys', 'GitHub Desktop', 'VS Code',
                         'Codex', 'Claude Code', 'ZCode'} <= groups)
        meetings = next(template for template in catalog['templates'] if template['name'] == 'Meetings')
        self.assertEqual(len(meetings['profile']['pages']['main']), 18)
        zcode = next(template for template in catalog['templates'] if template['name'] == 'ZCode')
        self.assertEqual(zcode['profile']['match'], ['zcode.exe'])

    def test_installed_program_inventory_is_available_after_login(self):
        self.login()
        programs = [{'name': 'Example', 'target': r'C:\\Example.lnk'}]
        with patch('tessera_app.installed_programs', return_value=programs):
            with self.request('/api/programs') as reply:
                self.assertEqual(json.load(reply), {'programs': programs})


if __name__ == '__main__':
    unittest.main()
