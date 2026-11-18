"""Local editor persistence, conflicts and browser security; no USB or OS actions."""
import copy
from http.cookiejar import CookieJar
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tessera_app
from tessera_app import Editor, make_server

# The three editor scripts run in node with a stand-in for the page, so a test calls the editor's own functions.
# The test script (stdin) is the body of an async function; what it returns is printed as JSON.
EDITOR_HARNESS = r'''
const vm = require('vm'), fs = require('fs'), path = require('path');
const stub = (store = new Map()) => new Proxy(function () {}, {
  get: (target, key) => store.has(key) ? store.get(key) : key === 'then' ? undefined : key === Symbol.toPrimitive ? () => ''
    : key === Symbol.iterator ? function* () {} : stub(),
  set: (target, key, value) => { store.set(key, value); return true; },
  apply: () => stub(), construct: () => stub()});
const storage = () => { const items = new Map(); return {getItem: key => items.has(key) ? items.get(key) : null, setItem: (key, value) => items.set(key, String(value))}; };
const nodes = new Map(), find = selector => nodes.get(selector) || nodes.set(selector, stub()).get(selector);
const document = stub();
Object.assign(document, {querySelector: find, getElementById: id => find('#' + id), querySelectorAll: () => []});
const context = vm.createContext({document, window: stub(), HTMLDialogElement: stub(), localStorage: storage(), sessionStorage: storage(),
  navigator: stub(), location: stub(), fetch: () => new Promise(() => {}), setTimeout: () => 0, clearTimeout: () => {},
  setInterval: () => 0, clearInterval: () => {}, requestAnimationFrame: () => 0, matchMedia: () => stub(), getComputedStyle: () => stub(),
  structuredClone, TextEncoder, console, settle: () => new Promise(done => setImmediate(done))});
for (const name of ['core', 'app', 'dialogs'])
  vm.runInContext(fs.readFileSync(path.join(process.argv[1], 'host/editor', name + '.js'), 'utf8'), context, {filename: name + '.js'});
vm.runInContext('(async () => {' + fs.readFileSync(0, 'utf8') + '\n})()', context).then(
  value => console.log(JSON.stringify(value)), error => { console.error(error.stack || error); process.exit(1); });
'''


def run_editor(test, script):
    node = shutil.which('node')
    if not node:
        test.skipTest('node is not installed')
    result = subprocess.run([node, '-e', EDITOR_HARNESS, str(ROOT)], input=script, capture_output=True,
                            text=True, encoding='utf-8', timeout=60)
    test.assertEqual(result.returncode, 0, result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


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
        self.session = ''

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        h = {'Content-Type': 'application/json', 'X-Deck-Request': '1', 'X-Deck-Session': self.session}
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

    def launch_code(self):
        address = self.server.launch_url()
        self.assertTrue(address.startswith(self.url + '/#'))
        return address.split('#', 1)[1]

    def login(self):
        with self.request('/api/session', {}, {'X-Deck-Launch': self.launch_code()}) as reply:
            self.assertIn('HttpOnly', reply.headers['Set-Cookie'])
            self.assertIn('SameSite=Strict', reply.headers['Set-Cookie'])
            self.session = json.load(reply)['session']

    def refused(self, path, data=None, headers=None):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(path, data, headers)
        error.exception.close()
        return error.exception.code

    def test_the_launch_address_works_once_and_never_carries_the_launcher_token(self):
        code = self.launch_code()
        self.assertNotIn('test-session-only', self.server.launch_url())
        self.assertEqual(self.refused('/api/session', {}, {'X-Deck-Launch': 'test-session-only'}), 403)
        with self.request('/api/session', {}, {'X-Deck-Launch': code}) as reply:
            self.assertTrue(json.load(reply)['session'])
        self.assertEqual(self.refused('/api/session', {}, {'X-Deck-Launch': code}), 403, 'a copy in the history is spent')
        # The launcher (its token is in the private record) asks for a fresh code to open a window
        with self.request('/api/session', {'launch': True}, {'X-Deck-Token': 'test-session-only'}) as reply:
            fresh = json.load(reply)['launch']
        self.assertNotEqual(fresh, code)
        with self.request('/api/session', {}, {'X-Deck-Launch': fresh}):
            pass
        self.assertEqual(self.refused('/api/session', {'launch': True}, {'X-Deck-Token': 'wrong'}), 403)

    def test_an_old_launch_code_expires(self):
        code = self.launch_code()
        with patch('tessera_app.time.monotonic', return_value=time.monotonic() + tessera_app.LAUNCH_CODE_SECONDS + 1):
            self.assertEqual(self.refused('/api/session', {}, {'X-Deck-Launch': code}), 403)

    def test_the_cookie_alone_is_not_a_session(self):
        # Cookies reach every port on 127.0.0.1: one leaked to another listener must not open the API.
        self.login()
        with self.request('/api/session', {}, {'X-Deck-Launch': self.launch_code()}) as reply:
            cookie = reply.headers['Set-Cookie']
        self.assertIn('Path=/api/image/', cookie)
        value = cookie.split(';', 1)[0].split('=', 1)[1]
        self.assertNotEqual(value, self.session)
        for header in ({'X-Deck-Session': ''}, {'X-Deck-Session': value}, {'X-Deck-Session': 'test-session-only'}):
            raw = {'Cookie': cookie.split(';', 1)[0], **header}
            self.assertEqual(self.refused('/api/config', headers=raw), 401)
            self.assertEqual(self.refused('/api/command/activate', {}, raw), 403)
        with self.request('/api/config') as reply:
            self.assertEqual(reply.status, 200)

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
        self.assertTrue(all(pack['actions'] or pack.get('states') for pack in catalog['packs']))  # a key that shows state keeps its steps in its states
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
        self.assertIn('id="auto-open"', more, 'automatic actions run in every profile, so they sit in More')
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
                 {'type': 'counter', 'name': 'laps', 'min': 1, 'max': 5}, {'type': 'set', 'variable': 'mode.1', 'value': 'x'},
                 {'type': 'script', 'path': 'C:\\scripts\\backup'}, {'type': 'script', 'path': 'scripts\\a.ps1'},
                 {'type': 'script', 'path': 'C:\\100%\\a.cmd'},
                 {'type': 'script', 'path': 'C:\\scripts\\a.ps1'}, {'type': 'script', 'path': '%USERPROFILE%\\a.cmd'},
                 {'type': 'script', 'path': ' "C:\\scripts\\a.ps1" '}]
        script = kinds + rules + f'console.log(JSON.stringify({json.dumps(steps)}.map(s=>!!stepProblem(s))));'
        result = subprocess.run([node, '-e', script], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [True] * 11 + [False] * 7 + [True] * 3 + [False] * 3)


class EditorScriptTests(unittest.TestCase):
    """The editor's own functions, run in node (run_editor)."""

    def test_a_power_pack_keeps_its_hold_to_confirm(self):
        found = run_editor(self, r'''
const power = {name: 'Shut down', icon: 'power', confirm: true, actions: [{type: 'shell', command: 'shutdown /s /t 0'}]};
const result = {};
for (const where of ['new', 'empty', 'hold']) {
  config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: []}}}}; profile = 'Main'; page = 'First'; selected = 1;
  actionCatalog.packs = [power];
  if (where === 'empty') config.profiles.Main.pages.First.push({id: 1, label: '', icon: 'ok', actions: []});
  if (where === 'hold') config.profiles.Main.pages.First.push({id: 1, label: 'X', icon: 'ok', actions: [], hold_actions: [{type: 'delay', ms: 1}]});
  addAction('pack:0', where === 'new' ? null : 1);
  result[where] = config.profiles.Main.pages.First.find(b => b.id === selected).confirm === true;
}
return result;
''')
        self.assertEqual(found, {'new': True, 'empty': True, 'hold': False})

    def test_editor_edits_never_leave_a_value_the_host_refuses(self):
        found = run_editor(self, r'''
const fresh = () => ({default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [], Second: []}}}});
const result = {};
config = fresh(); profile = 'Main'; page = 'First'; selected = 1; editState = 0;
config.profiles.Main.pages.First.push({id: 1, label: 'Mic', icon: 'ok', actions: [], bind: 'mic',
  states: [{label: 'Mic', actions: []}, {label: 'Mic on', actions: []}]});
const handlers = {}, realField = field;
field = (label, value, handler, options) => { handlers[label] = handler; return realField(label, value, handler, options); };
renderInspector();
field = realField;
handlers['Key type']('Normal key');
const key = config.profiles.Main.pages.First[0];
result.normal = {states: 'states' in key, bind: 'bind' in key};

config = fresh(); savedBase = clone(config); revision = 'r1'; dirty = true; conflicted = false;
let release = null;
const revisions = [];
api = async (path, data) => {
  if (!data) return {config: {...fresh(), display: {brightness: 40}}, revision: 'r2'};
  revisions.push(data.revision);
  if (revisions.length === 1) throw Object.assign(new Error('Changed elsewhere'), {status: 409});
  await new Promise(done => { release = done; });
  return {revision: 'r3'};
};
const saving = save();
await settle();
result.retry = {inFlight: saveInFlight !== null, revisions: [...revisions]};
release(); await saving;
result.retry.after = {inFlight: saveInFlight, revision, dirty};

const restored = {...fresh(), display: {brightness: 70}};
askDialog = async () => true;
api = async () => ({config: clone(restored), revision: 'r9'});
await restoreBackup({name: 'backup.json', saved: 'today'});
result.restore = {base: JSON.stringify(savedBase) === JSON.stringify(restored), separate: savedBase !== config};

config = fresh(); profile = 'Main'; page = 'First';
const limits = [], realDialog = dialog;
dialog = (title, fields) => { for (const item of fields) if (item.name === 'name') limits.push([title, item.maxLength]); };
api = async () => ({names: []});
newPage(); pageSettings(); await profileSettings();
dialog = realDialog;
result.limits = limits;
result.copy = uniqueName('x'.repeat(100), ['x'.repeat(90) + ' copy']).length;

config = fresh(); profile = 'Main'; page = 'Second';
config.triggers = [{when: {type: 'startup'}, actions: [{type: 'page', page: 'Second'}]}];
changePage('Later');
result.trigger = config.triggers[0].actions[0].page;

config = fresh(); profile = 'Main'; page = 'First';
const pinned = {id: 1, label: 'Pinned', icon: 'ok', actions: []};
config.profiles.Main.pinned = [pinned];
config.profiles.Main.pages.Second.push({id: 2, label: 'Other', icon: 'ok', actions: []});
const toasts = [];
toast = message => toasts.push(message);
setSpan(pinned, 2);
result.span = {span: pinned.span ?? null, told: toasts.length};

let asked = 0;
askDialog = async () => { asked++; return true; };
const plugin = {id: 'demo', name: 'Demo', version: '1.0.0', permissions: ['vars'], command: ['python', 'main.py']};
result.consent = [];
for (const variant of [plugin, plugin, {...plugin, command: ['python', 'other.py']}, {...plugin, permissions: ['vars', 'press']}, {...plugin, version: '1.0.1'}]) {
  await pluginConsent(variant);
  result.consent.push(asked);
}
return result;
''')
        self.assertEqual(found['normal'], {'states': False, 'bind': False}, 'a normal key keeps no bind: the host needs two states for one')
        self.assertEqual(found['retry'], {'inFlight': True, 'revisions': ['r1', 'r2'],
                                          'after': {'inFlight': None, 'revision': 'r3', 'dirty': False}},
                         'the merge retry is awaited, so finally cannot clear its saveInFlight')
        self.assertEqual(found['restore'], {'base': True, 'separate': True}, 'a restored backup is the base of the next merge')
        self.assertEqual([limit for _, limit in found['limits']], [100, 100, 100], 'profile and page names stay inside the host limit of 100')
        self.assertLessEqual(found['copy'], 100, 'a copy of a long name stays inside the host limit')
        self.assertEqual(found['trigger'], 'Later', 'triggers follow a page rename')
        self.assertEqual(found['span'], {'span': None, 'told': 1}, 'a wide pinned key must be free on every page')
        self.assertEqual(found['consent'], [1, 1, 2, 3, 4], 'a changed command, permission or version asks again')

    def test_an_undo_after_a_merge_keeps_what_another_program_saved(self):
        sent = run_editor(self, r'''
const base = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [{id: 1, label: 'Copy', icon: 'ok', actions: []}]}}}};
config = clone(base); savedBase = clone(base); revision = 'r1'; profile = 'Main'; page = 'First'; selected = 1;
mutate(() => { config.profiles.Main.pages.First[0].label = 'Edited'; });
const sent = [];
api = async (path, data) => {
  if (!data) return {config: {...clone(base), display: {brightness: 40}}, revision: 'r2'};  // the tray changed the brightness
  sent.push(clone(data.config));
  if (sent.length === 1) throw Object.assign(new Error('Changed elsewhere'), {status: 409});
  return {revision: 'r' + (sent.length + 1)};
};
await save();
undo(); await save();
undo(true); await save();
return sent.slice(1).map(item => [item.profiles.Main.pages.First[0].label, item.display ?? null]);
''')
        self.assertEqual(sent, [['Edited', {'brightness': 40}], ['Copy', {'brightness': 40}], ['Edited', {'brightness': 40}]])

    def test_automatic_actions_keep_unfinished_steps_out(self):
        found = run_editor(self, r'''
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: []}}}}; profile = 'Main'; page = 'First';
const toasts = [];
toast = message => toasts.push(message);
autoDraft = [{when: {type: 'startup'}, actions: [{type: 'open', target: ''}]}];
document.querySelector('#auto-apply').onclick();
const refused = {triggers: config.triggers ?? null, toasts: [...toasts]};
autoDraft = [{when: {type: 'startup'}, actions: [{type: 'open', target: 'notepad.exe'}]}];
document.querySelector('#auto-apply').onclick();
return {refused, saved: config.triggers};
''')
        self.assertIsNone(found['refused']['triggers'])
        self.assertIn('not finished', found['refused']['toasts'][0])
        self.assertEqual(found['saved'], [{'when': {'type': 'startup'}, 'actions': [{'type': 'open', 'target': 'notepad.exe'}]}])

    def test_plugin_settings_store_the_defaults_the_fields_show(self):
        manifest = json.loads((ROOT / 'plugins/home-assistant/plugin.json').read_text(encoding='utf-8'))
        found = run_editor(self, f'''
config = {{default_profile: 'Main', profiles: {{Main: {{match: [], pages: {{First: []}}}}}}}}; profile = 'Main'; page = 'First';
const plugin ={{...{json.dumps(manifest)}, values: {{}}}};
setPlugin(plugin, {{settings: {{token: 'abc'}}}});
setPlugin(plugin, {{enabled: true}});
const first = clone(config.plugins[plugin.id]);
config.plugins[plugin.id].settings.url = 'http://ha.lan:8123';
setPlugin(plugin, {{enabled: false}});
return {{first, kept: config.plugins[plugin.id].settings.url}};
''')
        self.assertEqual(found['first'], {'enabled': True, 'settings': {
            'url': 'http://homeassistant.local:8123', 'token': 'abc', 'entities': '', 'interval': 10}})
        self.assertEqual(found['kept'], 'http://ha.lan:8123', 'a stored value wins over the default')

    def test_the_editor_and_the_host_agree_on_plugin_steps(self):
        """config_check measures args with Python's json.dumps: spaces after , and : and non-ASCII as \\uXXXX."""
        pad = 'x' * (1024 - len(json.dumps({'k': ['', 'y']})))
        steps = [{'plugin': 'obs', 'command': 'record'}, {'plugin': 'obs', 'command': 'scene', 'args': {'name': 'Gaming'}},
                 {'plugin': 'home-assistant', 'command': 'call', 'args': {'service': 'scene.turn_on', 'n': None, 'b': True, 'f': 1.5}},
                 {'plugin': 'obs', 'command': 'volume-up', 'args': {'k': [pad, 'y']}},
                 {'plugin': 'obs', 'command': 'x', 'args': {'t': '\U0001F600' * 84}},
                 {'plugin': '', 'command': 'record'}, {'plugin': 'OBS', 'command': 'record'}, {'plugin': 'o', 'command': 'record'},
                 {'plugin': 'obs'}, {'plugin': 'obs', 'command': ''}, {'plugin': 'obs', 'command': 'rec ord'},
                 {'plugin': 'obs', 'command': 'x' * 65}, {'plugin': 'obs', 'command': 'x', 'args': []},
                 {'plugin': 'obs', 'command': 'x', 'args': 'name'}, {'plugin': 'obs', 'command': 'x', 'args': {'k': [pad + 'x', 'y']}},
                 {'plugin': 'obs', 'command': 'x', 'args': {'t': 'æ' * 200}}, {'plugin': 'obs', 'command': 'x', 'args': {'t': '\U0001F600' * 85}},
                 {'plugin': 'obs', 'command': 'x', 'args': {'t': '\x7f' * 170}}]
        steps = [{'type': 'plugin', **step} for step in steps]

        def host_takes(step):
            try:
                tessera_app.validate_config({'default_profile': 'p', 'profiles': {'p': {'match': [], 'pages': {
                    'page': [{'id': 1, 'label': 'Key', 'actions': [step]}]}}}})
                return True
            except ValueError:
                return False

        expected = [host_takes(step) for step in steps]
        self.assertEqual(expected, [True] * 5 + [False] * 13, 'the cases cover both sides of each rule')
        self.assertEqual(run_editor(self, f'return {json.dumps(steps)}.map(step => !stepProblem(step));'), expected)

    def test_a_plugin_step_has_its_own_fields_and_refuses_bad_arguments(self):
        found = run_editor(self, r'''
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [{id: 1, label: 'Rec', icon: 'ok',
  actions: [{type: 'plugin', plugin: 'obs', command: 'record'}]}]}}}};
profile = 'Main'; page = 'First'; selected = 1; editState = 0;
const step = config.profiles.Main.pages.First[0].actions[0];
const result = {template: actionTemplate('plugin').actions[0], name: kindName('plugin'), detail: stepDetail(step), types: Object.keys(kinds).includes('plugin')};
const fields = {}, toasts = [], realField = field, realElement = element;
const area = {value: '', attrs: {}, setAttribute(key, value) { this.attrs[key] = value; }, addEventListener(type, fn) { this.change = fn; }};
field = (label, value, handler, options) => { fields[label] = {value, handler, values: options?.values ?? null}; return realField(label, value, handler, options); };
element = (tag, ...rest) => tag === 'textarea' ? area : realElement(tag, ...rest);
toast = message => toasts.push(message);
setPluginChoices([{id: 'obs', name: 'OBS Studio', enabled: true}, {id: 'home-assistant', name: 'Home Assistant', enabled: false}]);
renderStep(step, 0, 1);
result.listed = fields.Plugin.values;
step.plugin = 'my-plugin'; renderStep(step, 0, 1); result.unlisted = fields.Plugin.values.at(-1);
setPluginChoices([]); renderStep(step, 0, 1); result.typed = fields.Plugin.values;
fields.Command.handler(' scene ');
area.value = '{"name": "Gaming"}'; area.change();
result.saved = clone(step); result.valid = area.attrs['aria-invalid'];
for (const bad of ['{"name": ', '[1]', JSON.stringify({text: 'x'.repeat(1100)})]) { area.value = bad; area.change(); }
field = realField; element = realElement;
result.after = clone(step); result.invalid = area.attrs['aria-invalid']; result.toasts = toasts;
return result;
''')
        self.assertEqual(found['template'], {'type': 'plugin', 'plugin': '', 'command': '', 'args': {}})
        self.assertEqual((found['name'], found['detail'], found['types']), ('Plugin command', 'Plugin command: obs record', True))
        self.assertEqual(found['listed'], [['', 'Choose a plugin'], ['obs', 'OBS Studio'], ['home-assistant', 'Home Assistant (off)']])
        self.assertEqual(found['unlisted'], ['my-plugin', 'my-plugin'], 'a plugin that is not installed stays selectable')
        self.assertIsNone(found['typed'], 'with no plugin installed the id is typed')
        self.assertEqual(found['saved'], {'type': 'plugin', 'plugin': 'my-plugin', 'command': 'scene', 'args': {'name': 'Gaming'}})
        self.assertEqual(found['valid'], 'false')
        self.assertEqual(found['after'], found['saved'], 'refused arguments never reach the key')
        self.assertEqual(found['invalid'], 'true')
        self.assertEqual(len(found['toasts']), 3)
        self.assertIn('JSON', found['toasts'][0])
        self.assertIn('object', found['toasts'][1])
        self.assertIn('1024', found['toasts'][2])

if __name__ == '__main__':
    unittest.main()
