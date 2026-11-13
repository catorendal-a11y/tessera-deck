"""OBS Studio on the panel: switch scenes, start and stop recording and streaming, mute an input.

Turn on OBS's WebSocket server (Tools → WebSocket Server Settings) and put its port and password in this plugin's
settings (editor: More → Plugins … → OBS Studio). OBS must run on the same PC.

Keys:   {"type": "plugin", "plugin": "obs", "command": "scene", "args": {"name": "Gaming"}}
        {"type": "plugin", "plugin": "obs", "command": "record"}     (start or stop)
        {"type": "plugin", "plugin": "obs", "command": "stream"}     (start or stop)
        {"type": "plugin", "plugin": "obs", "command": "mute", "args": {"input": "Mic/Aux"}}
Names:  $(var:obs.scene), $(var:obs.recording) and $(var:obs.streaming) (ON or OFF), $(var:obs.connected)
Colour: "status": {"var": "obs.recording", "colors": {"ON": "#FF7070"}}

It speaks OBS WebSocket 5 with a small client built on the Python standard library. The password is left out
when you export your keys.
"""
import base64
import hashlib
import json
import os
import socket
import struct
import threading
import time
import urllib.error
import urllib.request

API = os.environ['TESSERA_API']
TOKEN = os.environ['TESSERA_TOKEN']
PLUGIN = os.environ['TESSERA_PLUGIN']
SETTINGS = json.loads(os.environ.get('TESSERA_SETTINGS') or '{}')
PORT = int(SETTINGS.get('port') or 4455)
PASSWORD = str(SETTINGS.get('password') or '')
SUBSCRIBE = 1 | 4 | 64 | 8  # general, scenes, outputs and inputs events


def tessera(method, path, data=None, timeout=35):
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(API + path, data=body, method=method,
                                     headers={'X-Deck-Token': TOKEN, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.loads(reply.read())


def show(**values):
    tessera('POST', '/v1/vars', {'set': {f'{PLUGIN}.{name}': str(value)[:40] for name, value in values.items()}})


class Obs:
    """Just enough WebSocket (RFC 6455) for OBS on localhost: text frames, ping and close."""

    def __init__(self, port):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=5)
        self.lock = threading.Lock()
        self.buffer = b''
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f'GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                           f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n'
                           'Sec-WebSocket-Protocol: obswebsocket.json\r\n\r\n').encode())
        while b'\r\n\r\n' not in self.buffer:
            self.buffer += self._receive()
        head, self.buffer = self.buffer.split(b'\r\n\r\n', 1)
        if b' 101 ' not in head.split(b'\r\n', 1)[0]:
            raise ConnectionError('OBS refused the connection')
        self.sock.settimeout(None)
        self.requests = 0

    def _receive(self):
        data = self.sock.recv(65536)
        if not data:
            raise ConnectionError('OBS closed the connection')
        return data

    def _exactly(self, count):
        while len(self.buffer) < count:
            self.buffer += self._receive()
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def _frame(self, opcode, payload):
        mask = os.urandom(4)
        size = len(payload)
        head = bytes([0x80 | opcode]) + (bytes([0x80 | size]) if size < 126 else
                                         bytes([0x80 | 126]) + struct.pack('>H', size) if size < 65536 else
                                         bytes([0x80 | 127]) + struct.pack('>Q', size))
        with self.lock:
            self.sock.sendall(head + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload)))

    def send(self, message):
        self._frame(0x1, json.dumps(message).encode())

    def read(self):
        """The next JSON message from OBS; answers pings on the way."""
        message = b''
        while True:
            first, second = self._exactly(2)
            size = second & 0x7F
            if size == 126:
                size = struct.unpack('>H', self._exactly(2))[0]
            elif size == 127:
                size = struct.unpack('>Q', self._exactly(8))[0]
            payload = self._exactly(size)
            opcode = first & 0x0F
            if opcode == 0x8:
                code = struct.unpack('>H', payload[:2])[0] if len(payload) >= 2 else 0
                raise ConnectionError('OBS did not accept the password' if code == 4009 else 'OBS closed the connection')
            if opcode == 0x9:
                self._frame(0xA, payload)
                continue
            if opcode in (0x0, 0x1):
                message += payload
                if first & 0x80:
                    return json.loads(message)

    def request(self, kind, data=None):
        self.requests += 1
        self.send({'op': 6, 'd': {'requestType': kind, 'requestId': str(self.requests), 'requestData': data or {}}})

    def identify(self):
        hello = self.read()['d']
        identify = {'rpcVersion': 1, 'eventSubscriptions': SUBSCRIBE}
        challenge = hello.get('authentication')
        if challenge:
            secret = base64.b64encode(hashlib.sha256((PASSWORD + challenge['salt']).encode()).digest()).decode()
            identify['authentication'] = base64.b64encode(hashlib.sha256((secret + challenge['challenge']).encode()).digest()).decode()
        self.send({'op': 1, 'd': identify})
        if self.read().get('op') != 2:
            raise ConnectionError('OBS did not accept the password')


def on_off(active):
    return 'ON' if active else 'OFF'


def follow_keys(obs, stop):
    """Second thread: Tessera's key commands become OBS requests."""
    since = tessera('GET', '/v1/events')['last']
    while not stop.is_set():
        reply = tessera('GET', f'/v1/events?since={since}&wait=20')
        for event in reply['events']:
            if event['type'] != 'command':
                continue
            command, args = event.get('command'), event.get('args') or {}
            if command == 'scene' and args.get('name'):
                obs.request('SetCurrentProgramScene', {'sceneName': str(args['name'])})
            elif command == 'record':
                obs.request('ToggleRecord')
            elif command == 'stream':
                obs.request('ToggleStream')
            elif command == 'mute' and args.get('input'):
                obs.request('ToggleInputMute', {'inputName': str(args['input'])})
        since = reply['last']


def session():
    obs = Obs(PORT)
    obs.identify()
    show(connected='yes')
    for kind in ('GetCurrentProgramScene', 'GetRecordStatus', 'GetStreamStatus'):
        obs.request(kind)
    stop = threading.Event()

    def keys_or_reconnect():
        _guarded(follow_keys, obs, stop)
        if not stop.is_set():  # keys no longer reach OBS: close, so the session starts again
            obs.sock.close()
    keys = threading.Thread(target=keys_or_reconnect, daemon=True)
    keys.start()
    try:
        while True:
            message = obs.read()
            data = message.get('d', {})
            if message.get('op') == 7:  # an answer to one of our requests
                answer, kind = data.get('responseData') or {}, data.get('requestType')
                if kind == 'GetCurrentProgramScene':
                    show(scene=answer.get('currentProgramSceneName', ''))
                elif kind == 'GetRecordStatus':
                    show(recording=on_off(answer.get('outputActive')))
                elif kind == 'GetStreamStatus':
                    show(streaming=on_off(answer.get('outputActive')))
            elif message.get('op') == 5:  # an event OBS sends by itself
                event, values = data.get('eventType'), data.get('eventData') or {}
                if event == 'CurrentProgramSceneChanged':
                    show(scene=values.get('sceneName', ''))
                elif event == 'RecordStateChanged':
                    show(recording=on_off(values.get('outputActive')))
                elif event == 'StreamStateChanged':
                    show(streaming=on_off(values.get('outputActive')))
    finally:
        stop.set()


def _guarded(work, *args):
    try:
        work(*args)
    except (urllib.error.URLError, OSError, ValueError):
        pass  # the main loop notices the closed connection and starts again


def main():
    while True:
        try:
            session()
        except (ConnectionError, OSError, ValueError) as exc:
            try:
                show(connected='OBS is not running' if isinstance(exc, (ConnectionRefusedError, TimeoutError, socket.timeout))
                     else str(exc)[:40], recording='OFF', streaming='OFF')
            except (urllib.error.URLError, OSError, ValueError):
                return  # Tessera itself is gone; it starts the plugin again
        time.sleep(5)  # OBS may start later: keep trying quietly


if __name__ == '__main__':
    main()
