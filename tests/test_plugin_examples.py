"""The bundled plugins: valid manifests, and the Home Assistant and OBS examples against fake servers."""
import base64
import hashlib
import importlib.util
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import struct
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import plugins  # noqa: E402


def load(name, settings):
    environment = {'TESSERA_API': 'http://127.0.0.1:9', 'TESSERA_TOKEN': 't', 'TESSERA_PLUGIN': name,
                   'TESSERA_SETTINGS': json.dumps(settings)}
    spec = importlib.util.spec_from_file_location(f'plugin_{name.replace("-", "_")}', ROOT / 'plugins' / name / 'main.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, environment):
        spec.loader.exec_module(module)
    return module


class ManifestTests(unittest.TestCase):
    def test_every_bundled_plugin_has_a_valid_manifest(self):
        found, errors = plugins.discover(ROOT / 'plugins')
        self.assertEqual(errors, [])
        self.assertLessEqual({'example-uptime', 'home-assistant', 'obs'}, {manifest.id for manifest in found})


class HomeAssistantTests(unittest.TestCase):
    def test_states_are_shown_and_a_key_toggles_an_entity(self):
        seen = []

        class Fake(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, data):
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                seen.append(('GET', self.path, self.headers.get('Authorization')))
                self.reply({'state': '21.5', 'attributes': {'unit_of_measurement': '°C'}} if 'sensor' in self.path
                           else {'state': 'on', 'attributes': {}})

            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                seen.append(('POST', self.path, json.loads(self.rfile.read(length))))
                self.reply([])

        server = ThreadingHTTPServer(('127.0.0.1', 0), Fake)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        module = load('home-assistant', {'url': f'http://127.0.0.1:{server.server_port}/', 'token': 'secret',
                                         'entities': 'light.kitchen, sensor.outdoor, bad entity'})
        self.assertEqual(module.states(), {'home-assistant.light.kitchen': 'on', 'home-assistant.sensor.outdoor': '21.5 °C'})
        self.assertEqual(seen[0][2], 'Bearer secret')
        module.run('toggle', {'entity': 'light.kitchen'})
        module.run('call', {'service': 'scene.turn_on', 'entity': 'scene.movie'})
        module.run('call', {'service': '../x', 'entity': 'scene.movie'})  # refused: not a service name
        self.assertEqual([item for item in seen if item[0] == 'POST'],
                         [('POST', '/api/services/homeassistant/toggle', {'entity_id': 'light.kitchen'}),
                          ('POST', '/api/services/scene/turn_on', {'entity_id': 'scene.movie'})])

    def test_many_entities_are_posted_in_batches_the_api_accepts(self):
        module = load('home-assistant', {'url': 'http://127.0.0.1:9/', 'token': 'secret'})
        calls = []
        values = {f'home-assistant.light.l{index}': 'on' for index in range(45)}
        with patch.object(module, 'tessera', lambda method, path, data=None: calls.append((path, data))):
            module.set_vars(values)
        self.assertEqual([len(data['set']) for _, data in calls], [20, 20, 5])
        self.assertEqual({path for path, _ in calls}, {'/v1/vars'})
        self.assertEqual({name: value for _, data in calls for name, value in data['set'].items()}, values)

    def test_a_refused_service_call_is_not_reported_as_unreachable(self):
        import urllib.error
        module = load('home-assistant', {'url': 'http://127.0.0.1:9/', 'token': 'secret'})
        error = lambda code: urllib.error.HTTPError('http://ha/api', code, 'x', {}, None)  # noqa: E731
        self.assertEqual(module.reason(error(401)), 'wrong token')
        self.assertEqual(module.reason(error(404)), 'HA error 404')
        self.assertEqual(module.reason(urllib.error.URLError('refused')), 'not reachable')


class FakeObs:
    """A WebSocket server that speaks just enough OBS WebSocket 5, with a password."""

    def __init__(self, password):
        self.password, self.salt, self.challenge = password, 'salt', 'challenge'
        self.server = socket.socket()
        self.server.bind(('127.0.0.1', 0))
        self.server.listen(1)
        self.server.settimeout(10)
        self.port = self.server.getsockname()[1]
        self.received = []
        threading.Thread(target=self.serve, daemon=True).start()

    def frame(self, connection, message):
        payload = json.dumps(message).encode()
        connection.sendall(bytes([0x81, len(payload)]) + payload if len(payload) < 126
                           else bytes([0x81, 126]) + struct.pack('>H', len(payload)) + payload)

    def read(self, connection):
        first, second = connection.recv(2)
        size = second & 0x7F
        if size == 126:
            size = struct.unpack('>H', connection.recv(2))[0]
        mask = connection.recv(4)
        data = b''
        while len(data) < size:
            data += connection.recv(size - len(data))
        return json.loads(bytes(byte ^ mask[i % 4] for i, byte in enumerate(data)))

    def serve(self):
        connection, _ = self.server.accept()
        request = b''
        while b'\r\n\r\n' not in request:
            request += connection.recv(1024)
        key = [line.split(b': ')[1] for line in request.split(b'\r\n') if line.lower().startswith(b'sec-websocket-key')][0]
        accept = base64.b64encode(hashlib.sha1(key + b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
        connection.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                           b'Sec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
        self.frame(connection, {'op': 0, 'd': {'rpcVersion': 1, 'authentication': {'salt': self.salt, 'challenge': self.challenge}}})
        identify = self.read(connection)['d']
        secret = base64.b64encode(hashlib.sha256((self.password + self.salt).encode()).digest()).decode()
        expected = base64.b64encode(hashlib.sha256((secret + self.challenge).encode()).digest()).decode()
        if identify.get('authentication') != expected:  # what OBS does: a close frame with code 4009
            connection.sendall(bytes([0x88, 2]) + struct.pack('>H', 4009))
            return
        self.frame(connection, {'op': 2, 'd': {'negotiatedRpcVersion': 1}})
        request = self.read(connection)['d']
        self.received.append(request)
        self.frame(connection, {'op': 7, 'd': {'requestType': request['requestType'], 'requestId': request['requestId'],
                                               'responseData': {'currentProgramSceneName': 'Gaming'}}})
        self.frame(connection, {'op': 5, 'd': {'eventType': 'RecordStateChanged', 'eventData': {'outputActive': True}}})


class ObsTests(unittest.TestCase):
    def test_the_plugin_signs_in_with_the_password_and_reads_answers_and_events(self):
        fake = FakeObs('hunter2')
        module = load('obs', {'port': fake.port, 'password': 'hunter2'})
        obs = module.Obs(fake.port)
        self.addCleanup(obs.sock.close)
        obs.identify()
        obs.request('GetCurrentProgramScene')
        answer = obs.read()
        self.assertEqual((answer['op'], answer['d']['responseData']['currentProgramSceneName']), (7, 'Gaming'))
        self.assertEqual(obs.read()['d']['eventData'], {'outputActive': True})
        self.assertEqual(fake.received[0]['requestType'], 'GetCurrentProgramScene')

    def test_a_wrong_password_is_refused(self):
        fake = FakeObs('hunter2')
        module = load('obs', {'port': fake.port, 'password': 'wrong'})
        obs = module.Obs(fake.port)
        self.addCleanup(obs.sock.close)
        with self.assertRaisesRegex(ConnectionError, 'did not accept the password'):
            obs.identify()

    def test_a_huge_frame_from_whatever_holds_the_port_is_refused_before_buffering(self):
        module = load('obs', {'port': 1})
        obs = object.__new__(module.Obs)  # a connected client without the handshake
        obs.sock, peer = socket.socketpair()
        self.addCleanup(obs.sock.close)
        self.addCleanup(peer.close)
        obs.buffer, obs.lock = b'', threading.Lock()
        obs.sock.settimeout(5)  # without the limit, read() would wait for 2**62 bytes
        peer.sendall(bytes([0x81, 127]) + struct.pack('>Q', 1 << 62) + b'x' * 1000)
        with self.assertRaisesRegex(ConnectionError, 'too much'):
            obs.read()


class ObsKeyTests(unittest.TestCase):
    """Key commands and OBS answers, with the socket and Tessera replaced by recorders."""

    def setUp(self):
        self.module = load('obs', {'port': 1, 'inputs': 'Mic/Aux, Desktop'})
        self.obs = object.__new__(self.module.Obs)
        self.obs.requests, self.obs.ids, self.obs.pending = 0, threading.Lock(), {}
        self.sent, self.shown, self.warned = [], [], []
        self.obs.send = self.sent.append
        for name, fake in (('show', lambda **values: self.shown.append(values)),
                           ('warn', lambda reason, buttons: self.warned.append((reason, list(buttons))))):
            patcher = patch.object(self.module, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def requests(self):
        return [(m['d']['requestType'], m['d']['requestData']) for m in self.sent]

    def answer(self, data=None, ok=True, comment=None, index=-1, code=604):
        """Reply to the latest request sent, or to the one at `index`."""
        request = self.sent[index]['d']
        status = {'result': ok, 'code': 100 if ok else code}
        if comment:
            status['comment'] = comment
        self.module.handle(self.obs, {'op': 7, 'd': {'requestType': request['requestType'], 'requestId': request['requestId'],
                                                    'requestStatus': status, 'responseData': data}})

    def test_simple_commands_map_to_obs_requests(self):
        for command in ('record', 'stream', 'replay', 'virtualcam', 'transition'):
            self.module.run(self.obs, command, None)
        self.module.run(self.obs, 'pause', {})
        self.module.run(self.obs, 'pause', {'mode': 'on'})
        self.module.run(self.obs, 'pause', {'mode': 'off'})
        self.module.run(self.obs, 'pause', {'mode': 'bogus'})  # ignored
        self.assertEqual([kind for kind, _ in self.requests()],
                         ['ToggleRecord', 'ToggleStream', 'SaveReplayBuffer', 'ToggleVirtualCam', 'TriggerStudioModeTransition',
                          'ToggleRecordPause', 'PauseRecord', 'ResumeRecord'])

    def test_show_and_hide_a_source_in_a_scene(self):
        self.module.run(self.obs, 'source', {'source': 'Webcam', 'scene': 'Gaming', 'mode': 'show'})
        self.assertEqual(self.requests(), [('GetSceneItemId', {'sceneName': 'Gaming', 'sourceName': 'Webcam'})])
        self.answer({'sceneItemId': 7})
        self.assertEqual(self.requests()[1], ('SetSceneItemEnabled', {'sceneName': 'Gaming', 'sceneItemId': 7, 'sceneItemEnabled': True}))
        self.module.run(self.obs, 'source', {'source': 'Webcam', 'scene': 'Gaming', 'mode': 'hide'})
        self.answer({'sceneItemId': 7})
        self.assertIs(self.requests()[-1][1]['sceneItemEnabled'], False)

    def test_toggling_a_source_flips_its_state_and_uses_the_current_scene(self):
        self.module.handle(self.obs, {'op': 5, 'd': {'eventType': 'CurrentProgramSceneChanged', 'eventData': {'sceneName': 'Chat'}}})
        self.module.run(self.obs, 'source', {'source': 'Webcam'})
        self.answer({'sceneItemId': 3})
        self.assertEqual(self.requests()[1], ('GetSceneItemEnabled', {'sceneName': 'Chat', 'sceneItemId': 3}))
        self.answer({'sceneItemEnabled': True})
        self.assertEqual(self.requests()[2], ('SetSceneItemEnabled', {'sceneName': 'Chat', 'sceneItemId': 3, 'sceneItemEnabled': False}))

    def test_a_source_key_without_any_scene_sends_nothing(self):
        self.module.run(self.obs, 'source', {'source': 'Webcam'}, 5)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.shown, [{'error': 'The current scene is not known yet'}])
        self.assertEqual(self.warned, [('The current scene is not known yet', [5])])

    def test_two_quick_volume_presses_move_two_steps(self):
        self.module.run(self.obs, 'volume-up', {'input': 'Mic/Aux', 'step': 3})
        self.module.run(self.obs, 'volume-up', {'input': 'Mic/Aux', 'step': 3})
        self.assertEqual(len(self.sent), 1)
        self.answer({'inputVolumeDb': -10.0})
        self.assertEqual(self.requests()[1][1]['inputVolumeDb'], -4.0)

    def test_a_second_toggle_of_the_same_source_waits_for_the_first(self):
        args = {'source': 'Webcam', 'scene': 'Gaming'}
        self.module.run(self.obs, 'source', args)
        self.module.run(self.obs, 'source', args)
        self.assertEqual(len(self.sent), 1)
        self.answer({'sceneItemId': 3})
        self.answer({'sceneItemEnabled': True})
        self.answer()
        self.module.run(self.obs, 'source', args)
        self.assertEqual(len(self.sent), 4)

    def test_failures_of_the_plugins_own_polls_are_not_reported(self):
        self.module.watch_inputs(self.obs)
        self.answer(ok=False, comment='No input was found', index=0)
        self.assertEqual(self.shown, [])

    def test_a_request_obs_never_answers_is_dropped_and_reported(self):
        self.module.run(self.obs, 'record', None)
        with patch.object(self.module.time, 'monotonic', lambda: 10 ** 9):  # the deadline has long passed
            self.module.run(self.obs, 'replay', None)
        self.assertEqual(self.shown, [{'error': 'OBS did not answer'}])
        self.assertEqual(len(self.obs.pending), 1)

    def test_inputs_that_share_a_variable_name_keep_the_first(self):
        with patch('sys.stderr'):
            self.assertEqual(self.module.unique_inputs(['Mic/Aux', 'Mic_Aux', 'Desktop']), ['Mic/Aux', 'Desktop'])

    def test_volume_steps_are_clamped_to_the_range_obs_accepts(self):
        self.module.run(self.obs, 'volume-up', {'input': 'Mic/Aux', 'step': 3})
        self.assertEqual(self.requests()[0], ('GetInputVolume', {'inputName': 'Mic/Aux'}))
        self.answer({'inputVolumeDb': -10.0, 'inputVolumeMul': 0.3})
        self.assertEqual(self.requests()[1], ('SetInputVolume', {'inputName': 'Mic/Aux', 'inputVolumeDb': -7.0}))
        self.module.run(self.obs, 'volume-up', {'input': 'Mic/Aux'})  # default step 2
        self.answer({'inputVolumeDb': 25.0})
        self.assertEqual(self.requests()[-1][1]['inputVolumeDb'], 26.0)
        self.module.run(self.obs, 'volume-down', {'input': 'Mic/Aux', 'step': 20})
        self.answer({'inputVolumeDb': -95.0})
        self.assertEqual(self.requests()[-1][1]['inputVolumeDb'], -100.0)

    def test_bad_args_are_ignored(self):
        for command, args in (('volume-up', {'input': 'Mic', 'step': 0}), ('volume-up', {'input': 'Mic', 'step': 999}),
                              ('volume-down', {'input': 'Mic', 'step': 'loud'}), ('volume-up', {'input': 'Mic', 'step': True}),
                              ('volume-up', {'step': 2}), ('mute', {'input': 'x' * 300}), ('scene', {'name': 5}),
                              ('source', {'source': 'a', 'scene': 's', 'mode': 'flip'}), ('record', 'not a dict'), ('nope', {})):
            self.module.run(self.obs, command, args)
        self.assertEqual([kind for kind, _ in self.requests()], ['ToggleRecord'])

    def test_a_refusal_from_obs_is_shown_and_the_next_success_clears_it(self):
        self.module.run(self.obs, 'replay', None)
        self.answer(ok=False, comment='Replay buffer is not running')
        self.assertEqual(self.shown, [{'error': 'Replay buffer is not running'}])
        self.module.run(self.obs, 'replay', None)
        self.answer()
        self.assertEqual(self.shown[-1], {'error': ''})

    def test_a_refusal_in_the_middle_of_a_source_key_stops_it(self):
        self.module.run(self.obs, 'source', {'source': 'Nope', 'scene': 'Gaming'})
        self.answer(ok=False, comment='No source was found')
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.shown, [{'error': 'No source was found'}])

    def test_a_refusal_is_said_on_the_panel_and_flashes_the_key_that_sent_it(self):
        self.module.run(self.obs, 'transition', None, 6)
        self.answer(ok=False, code=506)  # OBS sends this one without a comment
        self.module.run(self.obs, 'source', {'source': 'Cam', 'scene': 'Gaming'}, 4)
        self.answer({'sceneItemId': 3})
        self.answer(ok=False, comment='No scene item was found')  # a later step of the same key
        self.module.run(self.obs, 'replay', None, 7)
        self.answer(ok=False, code=501)  # OBS 33 when the replay buffer is set up but not started
        self.assertEqual(self.warned, [('Studio mode is off in OBS', [6]), ('No scene item was found', [4]),
                                       ('Replay buffer is not running', [7])])
        self.assertEqual(self.shown, [{'error': 'Studio mode is off in OBS'}, {'error': 'No scene item was found'},
                                      {'error': 'Replay buffer is not running'}])

    def test_mute_and_pause_state_follow_events_and_the_first_poll(self):
        self.module.watch_inputs(self.obs)
        self.assertEqual([data['inputName'] for _, data in self.requests()], ['Mic/Aux', 'Desktop'])
        self.answer({'inputMuted': True}, index=0)
        self.module.handle(self.obs, {'op': 5, 'd': {'eventType': 'InputMuteStateChanged',
                                                     'eventData': {'inputName': 'Desktop', 'inputMuted': False}}})
        self.module.handle(self.obs, {'op': 5, 'd': {'eventType': 'InputMuteStateChanged',
                                                     'eventData': {'inputName': 'Other', 'inputMuted': True}}})  # not watched
        self.module.handle(self.obs, {'op': 5, 'd': {'eventType': 'RecordStateChanged', 'eventData': {
            'outputActive': False, 'outputState': 'OBS_WEBSOCKET_OUTPUT_PAUSED'}}})  # what OBS 33 sends while paused
        self.module.handle(self.obs, {'op': 5, 'd': {'eventType': 'RecordStateChanged', 'eventData': {
            'outputActive': True, 'outputState': 'OBS_WEBSOCKET_OUTPUT_RESUMED'}}})
        self.assertEqual(self.shown, [{'mute.Mic_Aux': 'ON'}, {'mute.Desktop': 'OFF'},
                                      {'recording': 'ON', 'paused': 'ON'}, {'recording': 'ON', 'paused': 'OFF'}])

    def test_the_record_status_poll_sets_paused(self):
        self.module.handle(self.obs, {'op': 7, 'd': {'requestType': 'GetRecordStatus', 'requestId': '9',
                                                     'requestStatus': {'result': True, 'code': 100},
                                                     'responseData': {'outputActive': True, 'outputPaused': True}}})
        self.assertEqual(self.shown, [{'recording': 'ON', 'paused': 'ON'}])

    def test_unanswered_requests_are_capped(self):
        for _ in range(self.module.MAX_PENDING + 20):
            self.module.run(self.obs, 'record', None)
        self.assertEqual(len(self.obs.pending), self.module.MAX_PENDING)


class ObsAwayTests(unittest.TestCase):
    """Key presses while OBS cannot be reached: a warning on the panel and a red flash instead of nothing."""

    def setUp(self):
        self.module = load('obs', {'port': 1})
        self.posted = []

    def fake_tessera(self, batch, refuse=None):
        replies = iter([{'events': [], 'last': 5}, {'events': batch, 'last': 9}])

        def tessera(method, path, data=None):
            if method == 'POST':
                if refuse:
                    raise refuse
                self.posted.append((path, data))
                return {'ok': True}
            reply = next(replies, None)
            if reply is None:  # nothing new: the real route waits
                time.sleep(0.01)
                return {'events': [], 'last': 9}
            return reply
        return patch.object(self.module, 'tessera', tessera)

    def test_a_key_gets_one_warning_and_one_red_flash(self):
        batch = [{'type': 'command', 'command': 'record', 'button': 3}, {'type': 'command', 'command': 'stream', 'button': 3},
                 {'type': 'command', 'command': 'scene'}, {'type': 'press', 'button': 3}]
        with self.fake_tessera(batch):
            self.module.refuse_keys('OBS is not running', 0.1)
        self.assertEqual(self.posted, [('/v1/notify', {'text': 'OBS is not running', 'level': 'warn', 'seconds': 3}),
                                       ('/v1/feedback', {'button': 3, 'ok': False})])

    def test_other_events_get_no_warning(self):
        with self.fake_tessera([{'type': 'page', 'page': 'main'}]):
            self.module.refuse_keys('OBS is not running', 0.05)
        self.assertEqual(self.posted, [])

    def test_a_refused_warning_does_not_stop_the_plugin(self):
        import urllib.error
        refused = urllib.error.HTTPError('http://127.0.0.1:9/v1/notify', 403, 'Forbidden', {}, None)
        with self.fake_tessera([{'type': 'command', 'command': 'record', 'button': 1}], refuse=refused), \
                patch('sys.stderr'):
            self.module.refuse_keys('OBS is not running', 0.05)

    def test_main_answers_keys_between_attempts_and_ends_when_tessera_is_gone(self):
        import urllib.error
        shown = []
        with patch.object(self.module, 'session', side_effect=ConnectionRefusedError()), \
                patch.object(self.module, 'show', lambda **values: shown.append(values)), \
                patch.object(self.module, 'refuse_keys', side_effect=[None, urllib.error.URLError('gone')]) as refuse:
            self.module.main()
        self.assertEqual([c.args for c in refuse.call_args_list], [('OBS is not running', 5)] * 2)
        self.assertEqual(shown[0]['connected'], 'OBS is not running')

    def log_tessera(self, log):
        """Tessera's event route over a real EventLog; POSTs are recorded."""
        import urllib.parse

        def tessera(method, path, data=None):
            if method == 'POST':
                self.posted.append((path, data))
                return {'ok': True}
            query = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
            events, last = log.since(int(query.get('since', ['0'])[0]), 'obs', float(query.get('wait', ['0'])[0]),
                                     with_last=True)
            return {'events': events, 'last': last}
        return tessera

    def test_a_key_pressed_while_obs_is_tried_again_still_gets_the_warning(self):
        log = plugins.EventLog()
        with patch.object(self.module, 'tessera', self.log_tessera(log)):
            self.module.refuse_keys('OBS is not running', 0.05)
            log.add('command', plugin='obs', command='record', button=2)  # while the plugin tries to reach OBS
            self.module.refuse_keys('OBS is not running', 0.05)
        self.assertEqual(self.posted, [('/v1/notify', {'text': 'OBS is not running', 'level': 'warn', 'seconds': 3}),
                                       ('/v1/feedback', {'button': 2, 'ok': False})])

    def test_keys_obs_answered_in_a_session_get_no_warning_afterwards(self):
        self.module.refused_since = 0
        obs = MagicMock()
        obs.read.side_effect = ConnectionError('OBS closed the connection')  # connected, then OBS closes
        with patch.object(self.module, 'Obs', return_value=obs), patch.object(self.module, 'show'), \
                patch.object(self.module, 'follow_keys'), self.assertRaises(ConnectionError):
            self.module.session()
        self.assertIsNone(self.module.refused_since)

    def test_a_warning_is_one_short_line(self):
        with self.fake_tessera([]):
            self.module.warn('No source\nwas found ' + 'x' * 200, [3, None, 3])
        self.assertEqual(self.posted[0][1]['text'], ('No source was found ' + 'x' * 200)[:100])
        self.assertEqual(self.posted[1:], [('/v1/feedback', {'button': 3, 'ok': False})])

    def test_a_warning_drops_what_tessera_cannot_show(self):
        # OBS repeats the scene name from the key; the zero-width joiner in an emoji made Tessera refuse the banner
        with self.fake_tessera([]):
            self.module.warn('No source was found by the name of `\U0001F468‍\U0001F4BB Live`.', [2])
        text = self.posted[0][1]['text']
        self.assertEqual(text, 'No source was found by the name of `\U0001F468\U0001F4BB Live`.')
        self.assertTrue(text.isprintable())
        self.assertEqual(self.posted[1:], [('/v1/feedback', {'button': 2, 'ok': False})])

    def test_keys_pressed_before_the_plugin_looked_get_no_warning(self):
        log = plugins.EventLog()
        for index in range(150):  # more than one page of old events, with an OBS key among the newer ones
            log.add('command', plugin='obs', command='record', button=2) if index == 141 else log.add('press', button=1)
        tessera = self.log_tessera(log)
        for name, function in (('obs', 'tessera'), ('home-assistant', 'tessera'), ('example-uptime', 'call')):
            module = load(name, {})
            with patch.object(module, function, tessera):
                self.assertEqual(module.newest_event(), 150, name)
        with patch.object(self.module, 'tessera', tessera):
            self.module.refuse_keys('OBS is not running', 0.05)
        self.assertEqual(self.posted, [])

    def test_the_manifest_asks_for_the_banner_and_the_flash(self):
        manifest = plugins.load_manifest(ROOT / 'plugins' / 'obs')
        self.assertLessEqual({'notify', 'feedback'}, manifest.routes())


if __name__ == '__main__':
    unittest.main()
