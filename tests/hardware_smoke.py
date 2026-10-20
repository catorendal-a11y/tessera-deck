"""Explicit COM4 Deck-only hardware check; no PC actions are executed."""
import argparse
import json
from pathlib import Path
import time

import serial

ROOT = Path(__file__).resolve().parents[1]


class Panel:
    def __init__(self, port):
        self.ser = serial.Serial(port=port, baudrate=115200, timeout=.05, write_timeout=2,
                                 dsrdtr=False, rtscts=False)
        self.ser.dtr = self.ser.rts = False
        self.buffer = bytearray()
        self.events, self.lines = [], []

    def send_line(self, line):
        self.ser.write(line.encode() + b'\n')

    def wait_for(self, message_type, seconds=4, command=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.buffer.extend(self.ser.read(max(1, min(self.ser.in_waiting, 4096))))
            while b'\n' in self.buffer:
                line, _, rest = self.buffer.partition(b'\n')
                self.buffer = bytearray(rest)
                text = line.decode('utf-8', 'replace').strip()
                self.lines.append(text)
                if any(word in text for word in ('Guru Meditation', 'abort() was called', 'stack overflow')):
                    raise RuntimeError('The device restarted during the test')
                if message_type == 'config' and text.startswith('AD_CFG_END OK'):
                    return {'type': 'config'}
                if message_type == 'context' and text.startswith('AD_CONTEXT OK'):
                    return {'type': 'context'}
                if message_type == 'ui' and text.startswith('FQ_UI_STATUS '):
                    return json.loads(text.removeprefix('FQ_UI_STATUS '))
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if isinstance(message, dict) and message.get('type') == 'deck_event':
                    self.events.append(message)
                if (isinstance(message, dict) and message.get('type') == message_type and
                        (command is None or message.get('cmd') == command)):
                    return message
        raise TimeoutError('No response of type ' + message_type)

    def request(self, line, reply_prefix, seconds=3):
        """Send one console line and return the first reply line with the given prefix."""
        self.send_line(line)
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.buffer.extend(self.ser.read(max(1, min(self.ser.in_waiting, 4096))))
            while b'\n' in self.buffer:
                text, _, rest = self.buffer.partition(b'\n')
                self.buffer = bytearray(rest)
                text = text.decode('utf-8', 'replace').strip()
                self.lines.append(text)
                if text.startswith(reply_prefix):
                    return text
        raise TimeoutError('No reply starting with ' + reply_prefix)

    def config(self, buttons):
        payload = json.dumps({'buttons': buttons}, ensure_ascii=True)
        self.send_line('AD_CFG_BEGIN')
        for at in range(0, len(payload), 380):
            self.send_line('AD_CFG_DATA ' + payload[at:at + 380])
        self.send_line('AD_CFG_END')
        self.wait_for('config')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM4')
    parser.add_argument('--soak-seconds', type=int, default=20)
    args = parser.parse_args()
    panel = Panel(args.port)
    config = json.loads((ROOT / 'host/profiles.json').read_text(encoding='utf-8'))
    profile = config['profiles'][config['default_profile']]
    originals = [{k: button.get(k, '#35D07F' if k == 'color' else 'ok')
                  for k in ('id', 'label', 'icon', 'color', 'title')}
                 for button in next(iter(profile['pages'].values()))]
    try:
        panel.send_line('{"cmd":"get_info","heartbeat":true}')
        first = panel.wait_for('info')
        assert first['boardId'] == 'tessera-p4'
        panel.config([
            {'id': 1, 'label': 'USB "test"', 'icon': 'ok', 'color': '#35D07F'},
            {'id': 18, 'label': 'Slot 18 / é', 'icon': 'lc:e038', 'color': '#FFA868',
             'title': {'size': 20, 'position': 'top', 'bold': True}},
        ])
        panel.send_line('AD_CONTEXT ' + json.dumps(
            {'profile': 'hardware test', 'page': 'main', 'canBack': True}))
        panel.wait_for('context')
        assert panel.request('AD_BRIGHTNESS 50', 'AD_BRIGHTNESS ') == 'AD_BRIGHTNESS OK 50'
        assert panel.request('AD_DISPLAY_DIM 5', 'AD_DISPLAY_DIM ') == 'AD_DISPLAY_DIM OK 5'
        assert panel.request('AD_DISPLAY_WAKE', 'AD_DISPLAY_WAKE ').startswith('AD_DISPLAY_WAKE ESP_OK')
        assert panel.request('AD_BRIGHTNESS 0', 'AD_BRIGHTNESS ') == 'AD_BRIGHTNESS INVALID'
        assert panel.request('AD_BRIGHTNESS abc', 'AD_BRIGHTNESS ') == 'AD_BRIGHTNESS INVALID'
        assert panel.request('AD_DISPLAY_DIM 101', 'AD_DISPLAY_DIM ') == 'AD_DISPLAY_DIM INVALID'
        for _ in range(20):
            panel.send_line('AD_PRESS 1')
        end = time.monotonic() + 5
        while len(panel.events) < 20 and time.monotonic() < end:
            panel.wait_for('deck_event', seconds=1)
        assert len(panel.events) == 20
        assert all(event['label'] == 'USB "test"' for event in panel.events)
        panel.send_line('AD_PRESS 18')
        event = panel.wait_for('deck_event')
        assert event['button'] == 18 and event['label'] == 'Slot 18 / é'
        panel.send_line('FQ_UI_STATUS')
        ui = json.loads(panel.wait_for('ui')['labels'])
        assert ui['screen'] == 'deck' and ui['profile'] == 'hardware test'
        assert ui['page'] == 'main' and ui['canBack'] is True
        until = time.monotonic() + args.soak_seconds
        while time.monotonic() < until:
            panel.send_line('{"cmd":"get_info","heartbeat":true}')
            assert panel.wait_for('info')['bootId'] == first['bootId']
            time.sleep(.5)
        panel.request('AD_BRIGHTNESS ' + str(config.get('display', {}).get('brightness', 100)), 'AD_BRIGHTNESS ')
        panel.config(originals)
        panel.send_line('AD_CONTEXT ' + json.dumps(
            {'profile': config['default_profile'], 'page': next(iter(profile['pages'])), 'canBack': False}))
        panel.wait_for('context')
        panel.send_line('{"cmd":"get_info","heartbeat":true}')
        last = panel.wait_for('info')
        assert last['bootId'] == first['bootId'] and last['uptime'] >= first['uptime']
        print('Hardware passed: clean Deck screen, context, 21 button presses, brightness commands, UTF-8 and stable boot')
        print('Memory:', last['heap'], 'bytes internal,', last['psramFree'], 'bytes PSRAM free')
    finally:
        (ROOT / 'build/hardware-serial.log').write_text('\n'.join(panel.lines), encoding='utf-8')
        panel.ser.close()


if __name__ == '__main__':
    main()
