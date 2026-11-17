"""OBS Studio on the panel: scenes, sources, recording, streaming, replay buffer, virtual camera and audio.

Turn on OBS's WebSocket server (Tools → WebSocket Server Settings) and put its port and password in this plugin's
settings (editor: More → Plugins … → OBS Studio). OBS must run on the same PC. When OBS cannot be reached or refuses
a key (studio mode off, no replay buffer, a scene that does not exist), the key flashes red and the panel says why
for a few seconds.

Keys:   {"type": "plugin", "plugin": "obs", "command": "scene", "args": {"name": "Gaming"}}
        {"type": "plugin", "plugin": "obs", "command": "record"}          (start or stop)
        {"type": "plugin", "plugin": "obs", "command": "pause"}           (pause or resume recording)
        {"type": "plugin", "plugin": "obs", "command": "pause", "args": {"mode": "on"}}   (on, off or toggle)
        {"type": "plugin", "plugin": "obs", "command": "stream"}          (start or stop)
        {"type": "plugin", "plugin": "obs", "command": "replay"}          (save the replay buffer)
        {"type": "plugin", "plugin": "obs", "command": "virtualcam"}      (start or stop)
        {"type": "plugin", "plugin": "obs", "command": "transition"}      (studio mode: send preview to program)
        {"type": "plugin", "plugin": "obs", "command": "mute", "args": {"input": "Mic/Aux"}}
        {"type": "plugin", "plugin": "obs", "command": "source", "args": {"source": "Webcam", "scene": "Gaming", "mode": "toggle"}}
        {"type": "plugin", "plugin": "obs", "command": "volume-up", "args": {"input": "Mic/Aux", "step": 2}}
        {"type": "plugin", "plugin": "obs", "command": "volume-down", "args": {"input": "Mic/Aux", "step": 2}}
        "mode" for source is show, hide or toggle (default toggle); "scene" defaults to the current scene.
        "step" is in dB (default 2, up to 20); the volume stays between -100 and 26 dB.
Names:  $(var:obs.scene), $(var:obs.recording), $(var:obs.streaming) and $(var:obs.paused) (ON or OFF),
        $(var:obs.connected), $(var:obs.error) (the last refusal from OBS, empty after the next success),
        $(var:obs.mute.Mic_Aux) (ON when muted) for each input named in the "inputs" setting; characters
        other than letters, digits, dash and underscore in the input name become underscores.
Colour: "status": {"var": "obs.recording", "colors": {"ON": "#FF7070"}}

It speaks OBS WebSocket 5 with a small client built on the Python standard library. The password is left out
when you export your keys.
"""
import re
import base64
import hashlib
import json
import os
import socket
import struct
import sys
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
INPUTS = [name.strip() for name in str(SETTINGS.get('inputs') or '').split(',') if name.strip()][:10]
SUBSCRIBE = 1 | 4 | 64 | 8  # general, scenes, outputs and inputs events
MAX_NAME = 256  # longest scene, source or input name taken from a key
MAX_PENDING = 100  # requests still waiting for an answer from OBS
VOLUME_RANGE = (-100.0, 26.0)  # dB, what SetInputVolume accepts
DEFAULT_STEP, MAX_STEP = 2.0, 20.0
ANSWER_SECONDS = 5  # a request OBS has not answered by then is dropped
RETRY_SECONDS = 5  # between attempts to reach OBS
WARN_SECONDS = 3  # how long the panel says why a key did nothing
WARN_CHARS = 100  # the longest banner Tessera takes
# What OBS means by the refusals it sends without a comment. Of this plugin's requests only SaveReplayBuffer gets 501.
REFUSALS = {501: 'Replay buffer is not running', 502: 'Recording is already paused', 503: 'Recording is not paused',
            506: 'Studio mode is off in OBS'}
refused_since = None  # the last event refuse_keys answered; None once OBS answers keys itself
scene_now = ''  # the current program scene, for source keys that name no scene
volume_wait = {}  # input name -> (dB change gathered while its GetInputVolume is in flight, deadline)
toggle_wait = {}  # (scene, source) -> deadline while a toggle of that source is in flight
# OBS messages are a few kB. Whatever answers on the port (OBS closed, another program on it) cannot make
# this process buffer without end.
MAX_MESSAGE = 1024 * 1024


def tessera(method, path, data=None, timeout=35):
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(API + path, data=body, method=method,
                                     headers={'X-Deck-Token': TOKEN, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.loads(reply.read())


def newest_event():
    """The id to read events after, so only keys pressed from now on count. A reply holds at most 100 events, oldest
    first, so a full one is followed until the last page."""
    reply = tessera('GET', '/v1/events')
    while len(reply['events']) >= 100:
        reply = tessera('GET', f"/v1/events?since={reply['last']}")
    return reply['last']


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
            if len(self.buffer) > MAX_MESSAGE:
                raise ConnectionError('OBS sent too much')
            self.buffer += self._receive()
        head, self.buffer = self.buffer.split(b'\r\n\r\n', 1)
        if b' 101 ' not in head.split(b'\r\n', 1)[0]:
            raise ConnectionError('OBS refused the connection')
        self.sock.settimeout(None)
        self.requests = 0
        self.ids = threading.Lock()
        self.pending = {}

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
            if len(message) + size > MAX_MESSAGE:
                raise ConnectionError('OBS sent too much')
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

    def request(self, kind, data=None, then=None, quiet=False, key=None, refused=None):
        """Send a request. With `then`, it is called with OBS's answer data once the request succeeds.
        A failure or a missing answer is reported in obs.error unless the request is `quiet` (the plugin's own polls).
        A refusal is also shown on the panel, and `key` (the button that sent it) flashes red; `refused` is called then."""
        with self.ids:
            self.requests += 1
            number = str(self.requests)
            if then:
                if len(self.pending) >= MAX_PENDING:
                    self.pending.pop(next(iter(self.pending)))
                self.pending[number] = (then, time.monotonic() + ANSWER_SECONDS, quiet, key, refused)
        self.send({'op': 6, 'd': {'requestType': kind, 'requestId': number, 'requestData': data or {}}})

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
    since = newest_event()
    while not stop.is_set():
        reply = tessera('GET', f'/v1/events?since={since}&wait=20')
        for event in reply['events']:
            if event['type'] != 'command':
                continue
            run(obs, event.get('command'), event.get('args'), event.get('button'))
        since = reply['last']


def name_of(args, key):
    """A scene, source or input name from a key's args, or None when it is missing or unreasonable."""
    value = args.get(key)
    return value if isinstance(value, str) and 0 < len(value) <= MAX_NAME else None


def step_of(args):
    """The dB step of a volume key: a number above 0 and at most MAX_STEP, else None."""
    step = args.get('step', DEFAULT_STEP)
    if isinstance(step, bool) or not isinstance(step, (int, float)) or not 0 < step <= MAX_STEP:
        return None
    return float(step)


def done(_answer):
    show(error='')


def expire(obs):
    """Drop requests OBS never answered; one that a key started is reported in obs.error."""
    now = time.monotonic()
    with obs.ids:
        late = [number for number, entry in obs.pending.items() if entry[1] < now]
        lost = [obs.pending.pop(number) for number in late]
    if any(not entry[2] for entry in lost):
        show(error='OBS did not answer')


def run(obs, command, args, key=None):
    """One key command becomes one or more OBS requests. Bad args are ignored, like unknown commands."""
    expire(obs)
    args = args if isinstance(args, dict) else {}
    simple = {'record': 'ToggleRecord', 'stream': 'ToggleStream', 'replay': 'SaveReplayBuffer',
              'virtualcam': 'ToggleVirtualCam', 'transition': 'TriggerStudioModeTransition'}
    if command in simple:
        obs.request(simple[command], then=done, key=key)
    elif command == 'scene' and name_of(args, 'name'):
        obs.request('SetCurrentProgramScene', {'sceneName': args['name']}, done, key=key)
    elif command == 'mute' and name_of(args, 'input'):
        obs.request('ToggleInputMute', {'inputName': args['input']}, done, key=key)
    elif command == 'pause' and args.get('mode', 'toggle') in ('toggle', 'on', 'off'):
        obs.request({'toggle': 'ToggleRecordPause', 'on': 'PauseRecord', 'off': 'ResumeRecord'}[args.get('mode', 'toggle')],
                    then=done, key=key)
    elif command == 'source' and name_of(args, 'source') and args.get('mode', 'toggle') in ('toggle', 'show', 'hide'):
        scene = name_of(args, 'scene') or scene_now
        if scene:
            set_source(obs, scene, args['source'], args.get('mode', 'toggle'), key)
        else:
            show(error='The current scene is not known yet')
            warn('The current scene is not known yet', [key])
    elif command in ('volume-up', 'volume-down') and name_of(args, 'input') and step_of(args):
        change_volume(obs, args['input'], step_of(args) * (1 if command == 'volume-up' else -1), key)


def set_source(obs, scene, source, mode, key=None):
    """GetSceneItemId, then (for toggle) GetSceneItemEnabled, then SetSceneItemEnabled."""
    busy = (scene, source)
    release = None
    if mode == 'toggle':  # a second toggle while one is in flight would read the old state and undo nothing
        if toggle_wait.get(busy, 0) > time.monotonic():
            return
        toggle_wait[busy] = time.monotonic() + ANSWER_SECONDS

        def release():
            toggle_wait.pop(busy, None)

    def set_enabled(item, enabled):
        def finished(answer):
            toggle_wait.pop(busy, None)
            done(answer)
        obs.request('SetSceneItemEnabled', {'sceneName': scene, 'sceneItemId': item, 'sceneItemEnabled': enabled}, finished,
                    key=key, refused=release)

    def found(answer):
        item = answer.get('sceneItemId')
        if not isinstance(item, int) or item < 0:
            if release:
                release()
            return
        if mode == 'toggle':
            obs.request('GetSceneItemEnabled', {'sceneName': scene, 'sceneItemId': item},
                        lambda state: set_enabled(item, not state.get('sceneItemEnabled')), key=key, refused=release)
        else:
            set_enabled(item, mode == 'show')
    obs.request('GetSceneItemId', {'sceneName': scene, 'sourceName': source}, found, key=key, refused=release)


def change_volume(obs, name, change, key=None):
    """GetInputVolume, then SetInputVolume with the new dB value kept inside OBS's range."""
    waiting = volume_wait.get(name)
    if waiting and waiting[1] > time.monotonic():  # a read is in flight: this press adds to its step
        volume_wait[name] = (waiting[0] + change, waiting[1])
        return
    volume_wait[name] = (change, time.monotonic() + ANSWER_SECONDS)

    def got(answer):
        total = volume_wait.pop(name, (change, 0))[0]
        db = answer.get('inputVolumeDb')
        if isinstance(db, bool) or not isinstance(db, (int, float)):
            return
        low, high = VOLUME_RANGE
        obs.request('SetInputVolume', {'inputName': name, 'inputVolumeDb': round(min(high, max(low, db + total)), 2)}, done,
                    key=key)
    obs.request('GetInputVolume', {'inputName': name}, got, key=key, refused=lambda: volume_wait.pop(name, None))


def safe_name(name):
    return re.sub(r'[^A-Za-z0-9_-]', '_', name)[:40]


def unique_inputs(names):
    """Names that map to a variable no earlier name uses; the others are logged and left out."""
    kept, used = [], set()
    for name in names:
        if safe_name(name) in used:
            print(f'obs: input "{name}" gives obs.mute.{safe_name(name)} like an earlier one and is ignored', file=sys.stderr)
        else:
            used.add(safe_name(name))
            kept.append(name)
    return kept


INPUTS = unique_inputs(INPUTS)


def show_mute(name, muted):
    show(**{f'mute.{safe_name(name)}': on_off(muted)})


def watch_inputs(obs):
    for name in INPUTS:
        obs.request('GetInputMute', {'inputName': name}, lambda answer, name=name: show_mute(name, answer.get('inputMuted')),
                    quiet=True)


def handle(obs, message):
    """An answer to a request, or an event OBS sends by itself."""
    expire(obs)
    data = message.get('d', {})
    if message.get('op') == 7:
        status = data.get('requestStatus') or {}
        with obs.ids:
            entry = obs.pending.pop(data.get('requestId'), None)
        then = entry[0] if entry else None
        if not status.get('result', True):
            if entry and entry[4]:  # a key waiting for this answer must not keep waiting for one that never comes
                entry[4]()
            if then and not entry[2]:  # a key's request, or a step of one: say what OBS refused
                reason = status.get('comment') or REFUSALS.get(status.get('code')) or f"{data.get('requestType')} failed"
                show(error=reason)
                warn(reason, [entry[3]])
            return
        answer, kind = data.get('responseData') or {}, data.get('requestType')
        if then:
            then(answer)
        elif kind == 'GetCurrentProgramScene':
            show_scene(answer.get('currentProgramSceneName', ''))
        elif kind == 'GetRecordStatus':
            show(recording=on_off(answer.get('outputActive')), paused=on_off(answer.get('outputPaused')))
        elif kind == 'GetStreamStatus':
            show(streaming=on_off(answer.get('outputActive')))
    elif message.get('op') == 5:
        event, values = data.get('eventType'), data.get('eventData') or {}
        if event == 'CurrentProgramSceneChanged':
            show_scene(values.get('sceneName', ''))
        elif event == 'RecordStateChanged':  # OBS sends outputActive false while paused, but it still records
            paused = values.get('outputState') == 'OBS_WEBSOCKET_OUTPUT_PAUSED'
            show(recording=on_off(values.get('outputActive') or paused), paused=on_off(paused))
        elif event == 'StreamStateChanged':
            show(streaming=on_off(values.get('outputActive')))
        elif event == 'InputMuteStateChanged' and values.get('inputName') in INPUTS:
            show_mute(values['inputName'], values.get('inputMuted'))


def show_scene(name):
    global scene_now
    scene_now = name if isinstance(name, str) else ''
    show(scene=scene_now)


def session():
    global refused_since
    obs = Obs(PORT)
    obs.identify()
    refused_since = None  # keys from now on go to OBS; after this session, only newer ones get the warning
    volume_wait.clear()
    toggle_wait.clear()
    show(connected='yes')
    for kind in ('GetCurrentProgramScene', 'GetRecordStatus', 'GetStreamStatus'):
        obs.request(kind)
    watch_inputs(obs)
    stop = threading.Event()

    def keys_or_reconnect():
        _guarded(follow_keys, obs, stop)
        if not stop.is_set():  # keys no longer reach OBS: close, so the session starts again
            obs.sock.close()
    keys = threading.Thread(target=keys_or_reconnect, daemon=True)
    keys.start()
    try:
        while True:
            handle(obs, obs.read())
    finally:
        stop.set()


def _guarded(work, *args):
    try:
        work(*args)
    except (urllib.error.URLError, OSError, ValueError):
        pass  # the main loop notices the closed connection and starts again


def warn(reason, buttons):
    """A short warning on the panel and a red flash on each key that did nothing."""
    # Tessera refuses a banner with an unprintable character, and then the key would not flash either. OBS repeats the
    # name from the key, and an emoji in it can hold one (the zero-width joiner).
    text = ' '.join(''.join(char for char in reason if char.isprintable() or char.isspace()).split())
    try:
        tessera('POST', '/v1/notify', {'text': text[:WARN_CHARS], 'level': 'warn', 'seconds': WARN_SECONDS})
        for button in {button for button in buttons if isinstance(button, int)}:
            tessera('POST', '/v1/feedback', {'button': button, 'ok': False})
    except urllib.error.HTTPError as exc:  # refused (an old Tessera, too many at once): the next press tries again
        print(f'obs: Tessera refused the warning: HTTP {exc.code}', file=sys.stderr)


def refuse_keys(reason, seconds):
    """While OBS cannot be reached, a key gets a short warning on the panel and a red flash instead of doing nothing.
    It goes on from the last event the previous call saw, so a key pressed while OBS was tried again is answered too."""
    global refused_since
    deadline = time.monotonic() + seconds
    if refused_since is None:
        refused_since = newest_event()
    while (left := deadline - time.monotonic()) > 0:
        reply = tessera('GET', f'/v1/events?since={refused_since}&wait={left:.1f}')
        commands = [event for event in reply['events'] if event['type'] == 'command']
        refused_since = reply['last']
        if commands:  # one banner for a key with several OBS steps, and one flash per key
            warn(reason, [event.get('button') for event in commands])


def main():
    while True:
        try:
            session()
        except (ConnectionError, OSError, ValueError) as exc:
            reason = ('OBS is not running' if isinstance(exc, (ConnectionRefusedError, TimeoutError, socket.timeout))
                      else str(exc)[:40] or 'OBS cannot be reached')
            try:
                show(connected=reason, scene='', recording='OFF', streaming='OFF', paused='OFF', error='',
                     **{f'mute.{safe_name(name)}': '' for name in INPUTS})
                refuse_keys(reason, RETRY_SECONDS)  # OBS may start later: keep trying quietly
            except (urllib.error.URLError, OSError, ValueError):
                return  # Tessera itself is gone; it starts the plugin again


if __name__ == '__main__':
    main()
