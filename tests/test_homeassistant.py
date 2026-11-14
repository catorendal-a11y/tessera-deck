"""Home Assistant over the panel's ESPHome API ("api":1): settings, options, the key, ha_select, scopes and key leaks."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
import zipfile
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import host_support  # noqa: E402
import config_check  # noqa: E402
import diagnostics  # noqa: E402
import panel_serial  # noqa: E402
import plugins  # noqa: E402
from control_api import ControlServer  # noqa: E402
from test_wifi import FakeSerial  # noqa: E402

KEY = 'VGVzc2VyYSBjYW5hcnkga2V5IGZvciB0ZXN0cyAzMiE='  # base64 of a made-up 32-byte test value: it must reach only the editor
STATUS = {'type': 'api', 'enabled': True, 'clients': 1, 'ha': True, 'name': 'tessera-deck'}


class ApiSerial(FakeSerial):
    """FakeSerial whose get_info also says "api":1 (or leaves it out)."""
    api = 1

    def write(self, raw):
        if b'get_info' in raw:
            info = {'type': 'info', 'boardId': 'tessera-p4', 'firmwareVersion': '9.9.9', 'bootId': 1, 'protocol': 5}
            if self.api is not None:
                info['api'] = self.api
            with self.lock:
                self.written.extend(raw)
                self.pending.extend((json.dumps(info) + '\n').encode())
            return len(raw)
        return super().write(raw)


def open_panel(api=1, answers=None):
    ApiSerial.api, FakeSerial.answers = api, answers or {}
    with patch.object(panel_serial, 'serial', types.SimpleNamespace(Serial=ApiSerial)), \
            patch.object(panel_serial, 'HANDSHAKE_SECONDS', 0.5):
        return panel_serial.PanelSerial('COM9', Mock())


def answer_in_background(panel, reply, delay=0.05):
    def run():
        time.sleep(delay)
        panel.api_key_reply = reply
        panel.api_key_done.set()
    threading.Thread(target=run, daemon=True).start()


class Rules(unittest.TestCase):
    def test_settings_get_defaults_and_the_set_line_is_compact_ascii(self):
        self.assertEqual(panel_serial.homeassistant_settings({}), panel_serial.API_DEFAULTS)
        self.assertEqual(panel_serial.api_set_line({'enabled': True, 'friendly_name': 'Kjøkken', 'area': 'Hall'}),
                         'AD_API_SET {"enabled":true,"name":"tessera-deck","friendly":"Kj\\u00f8kken","area":"Hall"}')

    def test_invalid_settings(self):
        for settings in ({'enabled': 1}, {'name': 'Tessera'}, {'name': ''}, {'name': 'a' * 32}, {'name': 'a_b'},
                         {'friendly_name': ''}, {'friendly_name': 'x' * 61}, {'friendly_name': 'a\nb'},
                         {'area': 'x' * 41}, {'key': KEY}, [], None):
            with self.assertRaises(ValueError, msg=repr(settings)) as raised:
                panel_serial.homeassistant_settings(settings)
            self.assertIn('panel.homeassistant', str(raised.exception))
            self.assertNotIn(KEY, str(raised.exception))

    def test_options_keep_what_fits(self):
        names = ['Main', 'ø' * 16, 'x' * 32, 'tab\there', *[f'p{i}' for i in range(20)]]
        kept = panel_serial.api_options(names)
        self.assertEqual(kept[0], 'Main')
        self.assertNotIn('ø' * 16, kept)  # 32 bytes
        self.assertNotIn('x' * 32, kept)
        self.assertEqual(len(kept), 16)
        self.assertEqual(panel_serial.api_options_line(['A'], ['B', 'C']),
                         'AD_API_OPTIONS {"profiles":["A"],"pages":["B","C"]}')

    def test_key_and_status_parsing(self):
        self.assertEqual(panel_serial.parse_api_key('AD_API_KEY ' + KEY), KEY)
        for line in ('AD_API_KEY', 'AD_API_KEY FAILED storage', 'AD_API_KEY ' + KEY[:-2], 'AD_API_KEY ' + KEY + 'A', None):
            self.assertIsNone(panel_serial.parse_api_key(line), repr(line))
        self.assertEqual(panel_serial.parse_api_status(dict(STATUS, key=KEY, extra=1)),
                         {'enabled': True, 'clients': 1, 'ha': True, 'name': 'tessera-deck'})
        self.assertEqual(panel_serial.parse_api_status({'type': 'api', 'enabled': False, 'clients': -3, 'name': 'Bad Name'}),
                         {'enabled': False, 'clients': 0, 'ha': False})
        for message in ({'type': 'api'}, {'type': 'api', 'enabled': 'yes'}, {'type': 'wifi', 'enabled': True}, None):
            self.assertIsNone(panel_serial.parse_api_status(message), repr(message))

    def test_matches_compares_what_the_panel_reports(self):
        settings = panel_serial.homeassistant_settings({'enabled': True})
        self.assertTrue(panel_serial.api_matches(STATUS, settings))
        self.assertFalse(panel_serial.api_matches(dict(STATUS, enabled=False), settings))
        self.assertFalse(panel_serial.api_matches(dict(STATUS, friendly='Old name'), settings))
        self.assertFalse(panel_serial.api_matches(None, settings))


class PanelCommands(unittest.TestCase):
    def test_without_api_nothing_is_written(self):
        panel = open_panel(api=None)
        self.assertFalse(panel.supports_api())
        before = bytes(panel.ser.written)
        for call in (panel.api_key, panel.api_status):
            with self.assertRaises(RuntimeError):
                call()
        self.assertEqual(bytes(panel.ser.written), before)

    def test_key_and_new_key(self):
        panel = open_panel()
        self.assertTrue(panel.supports_api())
        start = len(panel.ser.written)
        answer_in_background(panel, 'AD_API_KEY ' + KEY)
        self.assertEqual(panel.api_key(), KEY)
        answer_in_background(panel, 'AD_API_KEY ' + KEY)
        self.assertEqual(panel.api_key(new=True), KEY)
        panel.api_status()
        self.assertEqual(bytes(panel.ser.written[start:]), b'AD_API_KEY\nAD_API_KEY NEW\nAD_API_STATUS\n')
        self.assertEqual(panel.api_key_reply, '')

    def test_a_malformed_answer_and_no_answer(self):
        panel = open_panel()
        answer_in_background(panel, 'AD_API_KEY ' + KEY[:30])
        with self.assertRaises(OSError) as raised:
            panel.api_key()
        self.assertNotIn(KEY[:30], str(raised.exception))
        with patch.object(panel_serial, 'WIFI_REPLY_SECONDS', 0.2), self.assertRaises(TimeoutError):
            panel.api_key()


class ConfigRules(unittest.TestCase):
    def config(self, homeassistant):
        config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        config['panel'] = dict(config.get('panel') or {}, homeassistant=homeassistant)
        return config

    def test_panel_homeassistant(self):
        config_check.validate_config(self.config({'enabled': True, 'name': 'desk-2', 'friendly_name': 'Desk', 'area': ''}))
        for settings in ({'enabled': True, 'key': KEY}, {'name': 'Desk'}, 'on'):
            with self.assertRaises(ValueError, msg=repr(settings)) as raised:
                config_check.validate_config(self.config(settings))
            self.assertIn('panel.homeassistant', str(raised.exception))


class DaemonSync(host_support.HostCase):
    def setUp(self):
        self.d = self.daemon()
        self.d.panel.supports_api.return_value = True
        self.d.connection_failed.clear()
        self.sent = []
        self.d.panel.send_line.side_effect = self.sent.append

    def test_options_once_and_again_on_a_new_page(self):
        self.d.api_tick()
        self.d.api_tick()
        options = [line for line in self.sent if line.startswith('AD_API_OPTIONS ')]
        self.assertEqual(len(options), 1)
        body = json.loads(options[0].removeprefix('AD_API_OPTIONS '))
        self.assertEqual(body['profiles'], list(self.d.config['profiles']))
        self.assertEqual(body['pages'], list(self.d.config['profiles'][self.d.profile]['pages']))
        self.d.config['profiles'][self.d.profile]['pages']['Extra'] = {'buttons': []}
        self.d.api_tick()
        self.assertEqual(len([line for line in self.sent if line.startswith('AD_API_OPTIONS ')]), 2)

    def test_settings_are_sent_only_when_the_panel_differs(self):
        self.d.config.setdefault('panel', {})['homeassistant'] = {'enabled': True}
        self.d.api_tick()
        self.assertFalse(any(line.startswith('AD_API_SET') for line in self.sent))  # no report from the panel yet
        self.d.api_state = panel_serial.parse_api_status(STATUS)
        self.d.api_tick()
        self.assertFalse(any(line.startswith('AD_API_SET') for line in self.sent))  # it already has it
        self.d.config['panel']['homeassistant'] = {'enabled': False}  # saved in the editor
        self.d.api_tick()
        self.d.api_tick()
        self.assertEqual([line for line in self.sent if line.startswith('AD_API_SET')],
                         ['AD_API_SET {"enabled":false,"name":"tessera-deck","friendly":"Tessera Deck","area":""}'])

    def test_a_reconnect_compares_again(self):
        self.d.config.setdefault('panel', {})['homeassistant'] = {'enabled': True, 'name': 'desk'}
        self.d.api_connected()
        self.d.panel.api_status.assert_called_once_with()
        self.d.api_state = panel_serial.parse_api_status(STATUS)
        self.d.api_tick()
        self.assertIn('AD_API_SET {"enabled":true,"name":"desk","friendly":"Tessera Deck","area":""}', self.sent)

    def test_no_config_block_sends_no_settings_and_old_panels_get_nothing(self):
        self.d.api_state = panel_serial.parse_api_status(STATUS)
        self.d.api_tick()
        self.assertFalse(any(line.startswith('AD_API_SET') for line in self.sent))
        self.sent.clear()
        self.d.api_options_sent = None
        self.d.panel.supports_api.return_value = False
        self.d.api_tick()
        self.assertEqual(self.sent, [])

    def test_ha_select(self):
        profiles = list(self.d.config['profiles'])
        self.d.switch_profile = Mock()
        self.d.switch_page = Mock()
        self.d.ha_select('profile', profiles[0])
        self.d.switch_profile.assert_called_once_with(profiles[0])
        page = next(iter(self.d.config['profiles'][self.d.profile]['pages']))
        self.d.ha_select('page', page)
        self.d.switch_page.assert_called_once_with(page)
        self.d.ha_select('profile', 'No such profile')
        self.d.ha_select('page', 'No such page')
        self.assertEqual(self.d.switch_profile.call_count, 1)
        self.assertEqual(self.d.switch_page.call_count, 1)


class ControlApiRoute(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.daemon = Mock()
        self.daemon.events = plugins.EventLog()
        self.daemon.connection_failed = threading.Event()
        self.daemon.api_state = {'enabled': True, 'clients': 0, 'ha': False}
        self.daemon.panel = Mock()
        self.daemon.panel.supports_api.return_value = True
        self.daemon.panel.api_key.return_value = KEY
        self.logged = []
        self.daemon.log = self.logged.append
        self.api = ControlServer(self.daemon, Path(temp.name) / 'api.json')
        self.api.start()
        self.addCleanup(self.api.stop)

    def call(self, data, token=None):
        request = urllib.request.Request(f'http://127.0.0.1:{self.api.server.server_port}/v1/api', method='POST',
                                         data=json.dumps(data).encode(),
                                         headers={'Content-Type': 'application/json', 'X-Deck-Token': token or self.api.token})
        try:
            with urllib.request.urlopen(request, timeout=3) as reply:
                return reply.status, json.loads(reply.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_the_owner_reads_the_key(self):
        self.assertEqual(self.call({'do': 'key'}), (200, {'api': self.daemon.api_state, 'key': KEY}))
        self.daemon.panel.api_key.assert_called_with(new=False)
        self.assertEqual(self.call({'do': 'new-key'})[0], 200)
        self.daemon.panel.api_key.assert_called_with(new=True)
        self.assertEqual(self.call({'do': 'status'}), (200, {'api': self.daemon.api_state}))
        self.assertFalse(any(KEY in line for line in self.logged), self.logged)
        self.assertIn('API owner POST /v1/api -> 200', self.logged)

    def test_a_plugin_is_refused_even_when_its_grant_lists_api(self):
        token = self.api.add_grant('sneaky', ['var', 'api'])
        self.assertEqual(self.call({'do': 'key'}, token)[0], 403)
        self.daemon.panel.api_key.assert_not_called()

    def test_conflicts_and_bad_input(self):
        self.assertEqual(self.call({'do': 'erase'})[0], 400)
        self.daemon.panel.api_key.side_effect = TimeoutError('The panel did not answer AD_API_KEY')
        self.assertEqual(self.call({'do': 'key'})[0], 409)
        self.daemon.panel.supports_api.return_value = False
        self.assertEqual(self.call({'do': 'key'}),
                         (409, {'error': 'The panel firmware does not support Home Assistant; update it'}))
        self.daemon.panel = None
        self.assertEqual(self.call({'do': 'status'}), (409, {'error': 'The panel is not connected'}))


class EditorCommand(unittest.TestCase):
    def test_panel_api_posts_to_the_host_and_writes_no_file(self):
        import tessera_app
        import deckctl
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        shutil.copyfile(ROOT / 'host/profiles.default.json', folder / 'profiles.json')
        editor = tessera_app.Editor(folder / 'profiles.json', dashboard=lambda: {'running': True, 'device': {}})
        before = {path: path.stat().st_mtime_ns for path in folder.iterdir()}
        info = {'pid': 1, 'port': 2, 'token': 't'}
        with patch.object(deckctl, 'load_info', return_value=info), \
                patch.object(deckctl, 'call', return_value={'api': {}, 'key': KEY}) as call:
            self.assertEqual(editor.command('panel-api', {'do': 'key'})['key'], KEY)
        self.assertEqual(call.call_args.args[:4], (info, 'POST', '/v1/api', {'do': 'key'}))
        self.assertEqual({path: path.stat().st_mtime_ns for path in folder.iterdir()}, before)
        with self.assertRaises(ValueError):
            editor.command('panel-api', {'do': 'erase'})


class KeyNeverLeaks(unittest.TestCase):
    """The key read through the control API and the daemon's reader loop reaches only the HTTP answer."""
    def test_canary(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        profiles = folder / 'profiles.json'
        shutil.copyfile(ROOT / 'host/profiles.default.json', profiles)
        daemon = host_support.test_daemon(profiles)
        daemon.args.verbose = True  # the most the host ever logs, including unknown panel lines
        panel = open_panel(1, {'AD_API_KEY': 'AD_API_KEY ' + KEY + '\n' + json.dumps(STATUS) + '\n'})
        daemon.panel, daemon.device_info = panel, dict(panel.info)
        output = io.StringIO()
        api = ControlServer(daemon, folder / 'deck-api.local.json')
        api.start()
        self.addCleanup(api.stop)
        reader = threading.Thread(target=daemon.reader_loop, args=(panel,), daemon=True)
        with contextlib.redirect_stdout(output):
            reader.start()
            request = urllib.request.Request(f'http://127.0.0.1:{api.server.server_port}/v1/api', method='POST',
                                             data=json.dumps({'do': 'key'}).encode(),
                                             headers={'Content-Type': 'application/json', 'X-Deck-Token': api.token})
            with urllib.request.urlopen(request, timeout=8) as reply:
                self.assertEqual(json.loads(reply.read())['key'], KEY)
            for _ in range(50):
                if daemon.api_state:
                    break
                time.sleep(0.02)
            daemon.publish_runtime(True, force=True)
            daemon.stop.set()
            reader.join(2)
        self.assertEqual(daemon.api_state, {'enabled': True, 'clients': 1, 'ha': True, 'name': 'tessera-deck'})
        runtime_text = (folder / 'deck-runtime.local.json').read_text(encoding='utf-8')
        runtime = json.loads(runtime_text)
        self.assertEqual((runtime['api'], runtime['api_state']['ha']), (1, True))
        log = output.getvalue()
        self.assertIn('API owner POST /v1/api -> 200', log)
        dashboard = {'running': True, 'device': {'connected': True, 'api': 1, 'api_state': runtime['api_state']}}
        bundle = diagnostics.build(folder / 'diag', json.loads(profiles.read_text(encoding='utf-8')), dashboard, '1.0',
                                   folder / 'missing.log')
        with zipfile.ZipFile(bundle) as archive:
            report = archive.read('report.json').decode('utf-8')
        self.assertIn('"ha": true', report)
        self.assertNotIn('tessera-deck"', report.split('"api_state"', 1)[1][:80])
        for text, where in ((log, 'log'), (runtime_text, 'runtime'), (profiles.read_text(encoding='utf-8'), 'profiles'),
                            (report, 'diagnostics')):
            self.assertNotIn(KEY, text, where)


if __name__ == '__main__':
    unittest.main()
