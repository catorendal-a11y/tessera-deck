"""Home Assistant on the panel: show the state of lights and sensors, switch them and run scenes from a key.

Settings (editor: More → Plugins … → Home Assistant): the address, a long-lived access token and the entities to show.

Show a state in a key name:  $(var:home-assistant.light.kitchen)  ->  on / off, or 21.5 for a sensor
Colour a key by it:           "status": {"var": "home-assistant.light.kitchen", "colors": {"on": "#FFB74D"}}
Switch something on a press:  {"type": "plugin", "plugin": "home-assistant", "command": "toggle",
                               "args": {"entity": "light.kitchen"}}
Run any service:              {"type": "plugin", "plugin": "home-assistant", "command": "call",
                               "args": {"service": "scene.turn_on", "entity": "scene.movie_night"}}

$(var:home-assistant.connected) is "yes" or a short reason. Only the Python standard library is used. The token is
left out when you export your keys.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ['TESSERA_API']
TOKEN = os.environ['TESSERA_TOKEN']
PLUGIN = os.environ['TESSERA_PLUGIN']
SETTINGS = json.loads(os.environ.get('TESSERA_SETTINGS') or '{}')
HOME = str(SETTINGS.get('url') or '').rstrip('/')
HOME_TOKEN = str(SETTINGS.get('token') or '')
ENTITIES = [item.strip() for item in str(SETTINGS.get('entities') or '').split(',') if item.strip()]
INTERVAL = max(2.0, float(SETTINGS.get('interval') or 10))
ENTITY = re.compile(r'[a-z_]+\.[a-z0-9_]+')  # also the shape of a service, domain.service
MAX_FAILURES = 5
MAX_VARS_PER_CALL = 20  # /v1/vars refuses more in one request


def tessera(method, path, data=None, timeout=35):
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(API + path, data=body, method=method,
                                     headers={'X-Deck-Token': TOKEN, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.loads(reply.read())


def set_vars(values):
    """Post the variables in batches: 20 or more entities in one call were refused, and every update failed."""
    items = list(values.items())
    for start in range(0, len(items), MAX_VARS_PER_CALL):
        tessera('POST', '/v1/vars', {'set': dict(items[start:start + MAX_VARS_PER_CALL])})


def home(method, path, data=None):
    """A call to Home Assistant's REST API with the token from the settings."""
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(HOME + path, data=body, method=method,
                                     headers={'Authorization': 'Bearer ' + HOME_TOKEN, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=8) as reply:
        return json.loads(reply.read() or b'null')


def states():
    """{'home-assistant.light.kitchen': 'on', ...} for the entities in the settings."""
    found = {}
    for entity in ENTITIES:
        if ENTITY.fullmatch(entity):
            try:
                state = home('GET', '/api/states/' + urllib.parse.quote(entity))
            except urllib.error.HTTPError as exc:
                if exc.code == 401:
                    raise
                state = None  # a misspelled entity must not hide the others
            if not isinstance(state, dict):
                found[f'{PLUGIN}.{entity}'[:64]] = 'unknown'
                continue
            unit = (state.get('attributes') or {}).get('unit_of_measurement', '')
            found[f'{PLUGIN}.{entity}'[:64]] = f"{state.get('state', '')}{' ' + unit if unit else ''}"[:40]
    return found


def run(command, args):
    """A key's command: toggle an entity, or call any service with an entity."""
    entity = str(args.get('entity', ''))
    if command == 'toggle' and ENTITY.fullmatch(entity):
        home('POST', '/api/services/homeassistant/toggle', {'entity_id': entity})
    elif command == 'call' and ENTITY.fullmatch(str(args.get('service', ''))):
        domain, service = str(args['service']).split('.', 1)
        home('POST', f'/api/services/{domain}/{service}', {'entity_id': entity} if entity else {})


def reason(exc):
    if isinstance(exc, urllib.error.HTTPError):  # the server answered, so it is reachable
        return 'wrong token' if exc.code == 401 else f'HA error {exc.code}'
    return 'not reachable'


def main():
    if not HOME or not HOME_TOKEN:
        tessera('POST', '/v1/vars', {'set': {f'{PLUGIN}.connected': 'add the address and token'}})
    since = tessera('GET', '/v1/events')['last']  # only react to presses from now on
    next_update, failures = 0.0, 0
    while failures < MAX_FAILURES:
        try:
            if HOME and HOME_TOKEN and time.monotonic() >= next_update:
                try:
                    values = dict(states(), **{f'{PLUGIN}.connected': 'yes'})
                except (urllib.error.URLError, OSError, ValueError) as exc:
                    values = {f'{PLUGIN}.connected': reason(exc)}
                set_vars(values)
                next_update = time.monotonic() + INTERVAL
            reply = tessera('GET', f'/v1/events?since={since}&wait={min(INTERVAL, 20):g}')
            for event in reply['events']:
                if event['type'] == 'command' and HOME and HOME_TOKEN:
                    try:
                        run(event.get('command'), event.get('args') or {})
                        next_update = 0.0  # show the new state at once
                    except (urllib.error.URLError, OSError, ValueError) as exc:
                        tessera('POST', '/v1/vars', {'set': {f'{PLUGIN}.connected': reason(exc)}})
            since = reply['last']
            failures = 0
        except (urllib.error.URLError, OSError, ValueError):
            failures += 1
            time.sleep(2)  # Tessera is busy or stopping; give up after a few tries so it restarts us


if __name__ == '__main__':
    main()
