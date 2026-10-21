"""Example Tessera plugin: shows how long it has been running and restarts the count on a `reset` command.

Use it in a key name as $(var:example-uptime.text). A key with the action
{"type": "plugin", "plugin": "example-uptime", "command": "reset"} restarts the count.
Only the Python standard library is used; copy this folder to start your own plugin.
"""
import json
import os
import time
import urllib.error
import urllib.request

API = os.environ['TESSERA_API']
TOKEN = os.environ['TESSERA_TOKEN']
PLUGIN = os.environ['TESSERA_PLUGIN']
SETTINGS = json.loads(os.environ.get('TESSERA_SETTINGS') or '{}')
INTERVAL = max(1.0, float(SETTINGS.get('interval', 5)))
MAX_FAILURES = 5


def call(method, path, data=None, timeout=35):
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(API + path, data=body, method=method,
                                     headers={'X-Deck-Token': TOKEN, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.loads(reply.read())


def clock_text(seconds):
    hours, rest = divmod(int(seconds), 3600)
    return f'{hours}:{rest // 60:02d}:{rest % 60:02d}'


def main():
    started = time.monotonic()
    since = call('GET', '/v1/events')['last']  # only react to events from now on
    next_update, failures = 0.0, 0
    while failures < MAX_FAILURES:
        try:
            if time.monotonic() >= next_update:
                call('POST', '/v1/vars', {'set': {f'{PLUGIN}.text': clock_text(time.monotonic() - started)}})
                next_update = time.monotonic() + INTERVAL
            reply = call('GET', f'/v1/events?since={since}&wait={min(INTERVAL, 20):g}')
            for event in reply['events']:
                if event['type'] == 'command' and event.get('command') == 'reset':
                    started = time.monotonic()
                    next_update = 0.0
            since = reply['last']
            failures = 0
        except (urllib.error.URLError, OSError, ValueError):
            failures += 1
            time.sleep(2)  # the host is busy or stopping; give up after a few tries so Tessera restarts us


if __name__ == '__main__':
    main()
