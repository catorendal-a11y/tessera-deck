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
import unittest
from unittest.mock import patch

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


if __name__ == '__main__':
    unittest.main()
