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

    def test_a_stalled_client_times_out_and_the_port_is_exclusive(self):
        import socket
        self.assertEqual(self.server.RequestHandlerClass.timeout, 10)
        with socket.socket() as second:
            second.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with self.assertRaises(OSError):
                second.bind(('127.0.0.1', self.server.server_port))

    def test_the_first_start_creates_the_profiles_from_the_defaults(self):
        folder = Path(self.temp.name) / 'fresh'
        folder.mkdir()
        (folder / 'profiles.default.json').write_text(json.dumps(self.config))
        editor = Editor(folder / 'profiles.json', dashboard=lambda: {})
        self.assertEqual(list(editor.read()['config']['profiles']), ['Main'])

    def test_setup_state_marks_a_fresh_deck_as_a_first_run_and_remembers_flags(self):
        folder = Path(self.temp.name) / 'setup'
        folder.mkdir()
        (folder / 'profiles.default.json').write_text(json.dumps(self.config))
        editor = Editor(folder / 'profiles.json', dashboard=lambda: {})
        self.assertEqual(editor.command('setup-state', {}), {'welcome_done': False})
        editor.command('setup-done', {'key_edited': True, 'firmware_hint_dismissed': '0.7.0'})
        (folder / 'profiles.json').write_text('{}')  # a later edit does not turn the first run off
        self.assertEqual(editor.command('setup-state', {}),
                         {'welcome_done': False, 'key_edited': True, 'firmware_hint_dismissed': '0.7.0'})
        for bad in ({'welcome_done': 'yes'}, {'anything': True}):
            with self.assertRaises(ValueError):
                editor.command('setup-done', bad)
        upgraded = Path(self.temp.name) / 'upgraded'
        upgraded.mkdir()
        (upgraded / 'profiles.default.json').write_text(json.dumps(self.config))
        (upgraded / 'profiles.json').write_text(json.dumps(dict(self.config, auto_profiles=False)))
        self.assertEqual(Editor(upgraded / 'profiles.json', dashboard=lambda: {}).command('setup-state', {}),
                         {'welcome_done': True})

    def login(self):
        with self.request('/api/session', {}, {'X-Deck-Token': 'test-session-only'}) as reply:
            self.assertIn('HttpOnly', reply.headers['Set-Cookie'])
            self.assertIn('SameSite=Strict', reply.headers['Set-Cookie'])

    def test_a_body_that_is_not_json_is_refused_in_english(self):
        self.login()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/config', {}, {'Content-Type': 'text/plain'})
        self.assertEqual(error.exception.code, 415)
        self.assertEqual(json.loads(error.exception.read())['error'], 'Expected JSON')
        error.exception.close()

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
        self.assertEqual(result['config'], dict(updated, version=2))  # saving stamps the schema version
        self.assertNotEqual(state['revision'], result['revision'])
        self.assertEqual(json.loads(self.path.with_name('profiles-previous.local.json').read_text()),
                         dict(self.config, version=2))

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
        terminal = json.loads(json.dumps(self.config))
        terminal['profiles']['Main']['pages']['First'][0]['label'] = 'Paste'  # a real change, not only new spacing
        self.path.write_text(json.dumps(terminal, indent=2))
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
        with self.request('/streamdeck.css') as reply:
            self.assertIn('text/css', reply.headers['Content-Type'])
            self.assertIn(b'compact, flat hardware-editor layout', reply.read())
        with self.request('/logo-mark.svg') as reply:
            self.assertIn('image/svg+xml', reply.headers['Content-Type'])
            self.assertIn(b'aria-label="Tessera"', reply.read())
        for path in ('/../host/profiles.json', '/api/command/execute'):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(path, {} if '/api/' in path else None)
            error.exception.close()

    def test_export_reports_what_it_left_out(self):
        self.path.write_text(json.dumps(dict(self.config, calendar={'url': 'https://example.invalid/basic.ics'})))
        self.login()
        with self.request('/api/export') as reply:
            bundle = json.load(reply)
        self.assertNotIn('calendar', bundle)
        self.assertEqual(bundle['left_out'], ['the calendar address'])
        self.assertEqual(bundle['redacted'], [])

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


class MarkupTests(unittest.TestCase):
    def test_the_deck_is_not_inside_the_more_menu(self):
        """A menu that was not closed swallowed the deck and squeezed it to the menu button's width."""
        from html.parser import HTMLParser
        found = {}

        class Walk(HTMLParser):
            stack = []

            def handle_starttag(self, tag, attrs):
                if tag == 'div':
                    classes = (dict(attrs).get('class') or '').split()
                    if 'deck-card' in classes:
                        found['inside'] = [frame for frame in self.stack if frame & {'more', 'more-menu'}]
                    self.stack.append(set(classes))

            def handle_endtag(self, tag):
                if tag == 'div' and self.stack:
                    self.stack.pop()

        Walk().feed((Path(__file__).resolve().parents[1] / 'host/editor/index.html').read_text(encoding='utf-8'))
        self.assertEqual(found.get('inside'), [])

    def test_keyboard_and_screen_reader_basics_are_in_the_markup(self):
        editor = Path(__file__).resolve().parents[1] / 'host/editor'
        html = (editor / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="shortcuts-bar"', html.split('</header>')[0], 'the shortcuts are visible in the app bar')
        self.assertIn('Ctrl+Y or Ctrl+Shift+Z', html, 'the redo tooltip names both shortcuts')
        self.assertIn('data-menu="move"', html, 'the key menu can move a key')
        screens = html[html.index('id="screens-view"'):].split('>')[0]
        self.assertNotIn('aria-live', screens, 'the screens view redraws every poll and must not be read out')
        css = (editor / 'cockpit.css').read_text(encoding='utf-8')
        before_media = css.split('@media')[0]  # a wide window may still change a token inside its media query
        self.assertEqual(before_media.count(':root{'), 1, 'one token block in cockpit.css')
        app = (editor / 'app.js').read_text(encoding='utf-8')
        for selector in ("'#library-tabs'", "'#inspector .inspector-tabs'"):
            self.assertIn(f'rovingTabs({selector}', app)

    def test_the_menus_put_each_setting_in_one_place(self):
        html = (Path(__file__).resolve().parents[1] / 'host/editor/index.html').read_text(encoding='utf-8')
        menu = lambda name: html.split(f'id="{name}"')[1].split('</div></div></div>')[0]
        panel = menu('panel-menu')
        self.assertLess(panel.index('id="display-open"'), panel.index('id="firmware-open"'))
        self.assertLess(panel.index('id="firmware-open"'), panel.index('id="rail-open"'))
        self.assertIn('Panel firmware and updates', panel)
        self.assertNotIn('panel-open', html, 'the rail screens choose what they show')
        self.assertIn('id="new-page-menu"', menu('page-menu'))
        self.assertIn('id="delete-page"', menu('page-menu'))
        self.assertIn('id="delete-profile"', menu('profile-menu'))
        more = menu('more-menu')
        self.assertNotIn('shortcuts-open', more, 'the app bar has the shortcuts')
        self.assertLess(more.index('id="welcome-open"'), more.index('id="claude-open"'))
        self.assertIn('Nothing runs in the editor. Keys run only when you press them on the panel.', html)

    def test_the_layout_makes_room_instead_of_shrinking_the_text(self):
        editor = Path(__file__).resolve().parents[1] / 'host/editor'
        self.assertIn('Math.max(1,', (editor / 'core.js').read_text(encoding='utf-8'), 'the zoom never goes below 1')
        css = (editor / 'cockpit.css').read_text(encoding='utf-8')
        self.assertIn('@media(min-width:1280px)', css, 'the key settings sit beside the deck from 1280 px')
        self.assertIn('--dim:#8FA0A8', css)
        self.assertIn('@media(prefers-contrast:more)', css)
        for sheet in ('style.css', 'streamdeck.css'):
            text = (editor / sheet).read_text(encoding='utf-8')
            self.assertNotIn('zoom:var(--z)', text, f'{sheet}: the zoom is set once, in cockpit.css')
            self.assertNotRegex(text, r'#deck-view\s*\{[^}]*grid-template-columns', f'{sheet}: the columns are set in cockpit.css')

    def test_a_step_the_host_would_refuse_stays_a_draft(self):
        """One bad value makes the host refuse the whole configuration, so the editor keeps such a step back like an empty one."""
        import shutil
        import subprocess
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        core = (ROOT / 'host/editor/core.js').read_text(encoding='utf-8')
        kinds = core[core.index('const kinds = {'):core.index('\n};', core.index('const kinds = {')) + 3]
        rules = core[core.index('function stepProblem'):core.index('function keyProblem')]
        steps = [{'type': 'press', 'id': 0}, {'type': 'press', 'id': 19}, {'type': 'state', 'button': 0, 'state': 'next'},
                 {'type': 'delay', 'ms': 60001}, {'type': 'hotkey', 'keys': 'ctrl+'}, {'type': 'http', 'url': 'example.com'},
                 {'type': 'counter', 'name': 'tæller'}, {'type': 'timer', 'name': 'my timer'}, {'type': 'set', 'variable': 'Mode 1'},
                 {'type': 'counter', 'name': 'laps', 'min': 5, 'max': 1}, {'type': 'timer', 'name': 'tea', 'seconds': 1.5},
                 {'type': 'press', 'id': 18}, {'type': 'delay', 'ms': 0}, {'type': 'hotkey', 'keys': 'ctrl+shift+b'},
                 {'type': 'http', 'url': 'https://example.com'}, {'type': 'http', 'url': '$(var:hook)'},
                 {'type': 'counter', 'name': 'laps', 'min': 1, 'max': 5}, {'type': 'set', 'variable': 'mode.1', 'value': 'x'}]
        script = kinds + rules + f'console.log(JSON.stringify({json.dumps(steps)}.map(s=>!!stepProblem(s))));'
        result = subprocess.run([node, '-e', script], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [True] * 11 + [False] * 7)

    def test_editor_edits_never_leave_a_value_the_host_refuses(self):
        editor = ROOT / 'host/editor'
        app, core, dialogs = ((editor / name).read_text(encoding='utf-8') for name in ('app.js', 'core.js', 'dialogs.js'))
        self.assertIn('delete base.states;delete base.bind;', app, 'a normal key keeps no bind: the host needs two states for one')
        self.assertIn('return await save();', core, 'the merge retry is awaited, so finally cannot clear its saveInFlight')
        self.assertIn("savedBase = clone(state.config)", dialogs, 'a restored backup is the base of the next merge')
        self.assertEqual(app.count('maxLength:100'), 4, 'profile and page names stay inside the host limit of 100')
        self.assertIn('base=String(base).slice(0,90)', core)
        self.assertIn('if(shared)for(const t of config.triggers', app, 'triggers follow a page rename in any profile')
        span = app[app.index('function setSpan'):app.index('function wideRows')]
        self.assertIn('freeOnAllPages(base.id, span, [base])', span, 'a wide pinned key must be free on every page')
        self.assertIn('[plugin.version, plugin.permissions, plugin.command', dialogs, 'a changed manifest asks again')

if __name__ == '__main__':
    unittest.main()
