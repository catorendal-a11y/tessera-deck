# Writing a Tessera plugin

[Back to the README](../README.md)

A plugin is a small program that adds values, key states and actions to Tessera. It runs as its own process, talks to Tessera over the local control API and can be written in any language. The source is `host/plugins.py` (manifests, lifecycle, events) and `host/control_api.py` (the API).

> **Trust.** A plugin runs with your own Windows rights. Tessera does not sandbox it. The limits below stop a plugin from using Tessera's API beyond what it declared. They do not stop it from doing anything else on your PC. Only install plugins you trust. See [Security](../SECURITY.md).

## The plugins that come with Tessera

Turn them on in **More → Plugins …**. All three use only the Python standard library.

| Plugin | What it does |
|---|---|
| `example-uptime` | The smallest complete plugin: a counter for a key name and a `reset` command. Copy it to start your own. |
| `home-assistant` | Shows the state of lights and sensors (`$(var:home-assistant.light.kitchen)`), toggles them and runs any service. Needs the address and a long-lived access token. |
| `obs` | Switches scenes, starts and stops recording and streaming, mutes an input, and shows the scene and *ON* or *OFF* in key names. Needs OBS's WebSocket server (Tools → WebSocket Server Settings). |

The top of each `main.py` lists the key actions and variable names it offers.

## A first plugin

A plugin is a folder in `plugins/` with a manifest and a program:

```text
plugins/
  example-uptime/
    plugin.json     the manifest
    main.py         your program
```

This is the manifest of `example-uptime`:

```json
{
  "id": "example-uptime",
  "name": "Example: uptime",
  "version": "1.0.0",
  "api": 1,
  "command": ["python", "main.py"],
  "permissions": ["vars", "events"],
  "settings": {
    "interval": { "type": "number", "label": "Seconds between updates", "default": 5 }
  }
}
```

This is the same idea in the fewest lines. The full `plugins/example-uptime/main.py` adds a retry limit and the `reset` command:

```python
import json, os, time, urllib.request

API, TOKEN, ME = os.environ['TESSERA_API'], os.environ['TESSERA_TOKEN'], os.environ['TESSERA_PLUGIN']

def call(method, path, data=None):
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(API + path, data=body, method=method,
                                     headers={'X-Deck-Token': TOKEN, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=35) as reply:
        return json.loads(reply.read())

started = time.monotonic()
while True:
    seconds = int(time.monotonic() - started)
    call('POST', '/v1/vars', {'set': {f'{ME}.text': f'{seconds // 60}:{seconds % 60:02d}'}})
    time.sleep(5)
```

To try it:

1. Put the folder in `plugins/`. The host notices it within a few seconds.
2. Turn the plugin on in **More → Plugins …**.
3. Name a key `$(var:example-uptime.text)`.
4. To restart the count from a key, add the action `{"type": "plugin", "plugin": "example-uptime", "command": "reset"}`. The full example reads it as an event.

## The manifest

| Field | Rules |
|---|---|
| `id` | 2 to 32 lowercase letters, digits or dashes, starting with a letter. Must equal the folder name. |
| `name`, `version` | Text of 1 to 60 characters. |
| `api` | Must be `1`. |
| `command` | The program and its arguments (1 to 12 words), run without a shell. `python` means Tessera's own interpreter. Anything else must be a file inside the plugin folder. |
| `permissions` | Any of `vars`, `press`, `feedback`, `state`, `events`, `read`. No duplicates. |
| `settings` | Up to 20 options. A key is lowercase letters, digits and underscores, starting with a letter (up to 32). `type` is `text`, `number` or `checkbox`; `label` and `default` are optional. The editor shows them in **Plugins …**. |

A folder with a bad manifest is skipped, and the editor shows the reason.

## Turning a plugin on

Turn it on in the editor, or in `profiles.json`:

```json
"plugins": { "my-plugin": { "enabled": true, "settings": { "interval": 10 } } }
```

- **Consent.** The first time you turn a plugin on, and again for a new `version`, the editor lists what it may do and the program it runs, and asks first. The editor remembers your answer in the browser. A profile file you import cannot turn plugins on or change their settings.
- **Secrets.** A setting whose key contains `token`, `secret`, `password` or `api_key` (any case) is stored encrypted for your Windows account with DPAPI. `profiles.json` and its backups hold `"$(dpapi:…)"` instead of the value. Your program receives the real value in `TESSERA_SETTINGS`. Exports leave these settings out.
- **Settings changes.** Changing a plugin's settings restarts it.

## What your program receives

Tessera starts the program with these environment variables. Of your own environment it passes on only `PATH` and basic Windows paths (`SYSTEMROOT`, `TEMP`, `APPDATA` and similar).

| Variable | Meaning |
|---|---|
| `TESSERA_API` | Base URL of the local API, for example `http://127.0.0.1:50321`. |
| `TESSERA_TOKEN` | Your own token. Send it as the `X-Deck-Token` header. |
| `TESSERA_PLUGIN` | Your id. |
| `TESSERA_SETTINGS` | The settings as JSON, with secrets decrypted. |

Output (stdout and stderr) goes to `host/plugins/<id>.log`. The log is kept as `.log.1` when it passes 1 MB.

## Lifecycle

- Tessera revokes a plugin's token when the plugin stops.
- A plugin that stops is started again after 1, 2, 4, 8, 16, 32 and then 60 seconds.
- After five crashes in a row it gives up and the editor shows the error. Turn the plugin off and on again, or change its settings, to start it again. A plugin that runs for 60 seconds counts as stable and its crash count starts from zero.
- Turning a plugin off stops it.

## The API

Every request needs `X-Deck-Token`. The host answers only to the `Host` header `127.0.0.1:<port>` and rejects any request with an `Origin` header. Bodies are JSON objects of at most 64 KB.

### Permissions

| Permission | Allows |
|---|---|
| `vars` | `POST /v1/var` and `POST /v1/vars`, **only for names starting with `<id>.`** |
| `press` | `POST /v1/press` with `{"button": 1-18}` presses a key. |
| `feedback` | `POST /v1/feedback` with `{"button": 1-18, "ok": true}` flashes a key green, or red with `false`. |
| `state` | `POST /v1/state` with `{"button": 1-18, "state": "next" or 0-7}` sets a toggle key's state. |
| `events` | `GET /v1/events` reads key presses, page changes and commands. |
| `read` | `GET /v1/state` reads the host state: profile, page, connection, variables, agents and queue sizes. |

The routes `page`, `display` and `permission` are for the owner token only. No plugin can use them.

### Answers

| Code | Meaning |
|---|---|
| `200` | Done. Changes answer `{"ok": true, "queued": true}`. |
| `400` | The request is invalid. `error` says why. |
| `401` | The token is unknown. |
| `403` | The token lacks the permission, the variable name does not start with `<id>.`, or the `Host` or `Origin` header is wrong. |
| `413` | The body is too large. |
| `429` | Too many calls. Each token may make 20 calls a second, in bursts of up to 40. The answer has `"retry": true`. |
| `503` | The host's work queue is full. The answer has `"retry": true`. Try again shortly. |

Every call that changes something is written to the host log with the plugin's id, the method, the path and the answer code (never the body). Successful variable updates are left out.

## Showing values and changing keys

Set variables with `POST /v1/vars` and `{"set": {"my-plugin.text": "42"}}`: 1 to 20 variables, names of 1 to 64 letters, digits, dots, dashes or underscores, values of text or a number up to 200 characters. Then name a key `$(var:my-plugin.text)`. A key's `status` setting colors it from a variable. A toggle key follows the `state` route.

## Reacting to keys: events

`GET /v1/events?since=<last id>&wait=<seconds>` returns `{"events": [...], "last": <id>}`. Start with `since=0` or omit it, and pass the returned `last` as the next `since`. The request waits up to `wait` seconds (at most 25) for news, so one loop is enough. Tessera keeps the last 200 events and returns at most 100 at a time. Every event also has `id`, `type` and `at` (Unix time).

| `type` | Fields |
|---|---|
| `press` | `button`, `label`, `profile`, `page`, `ok`, `hold`, `double` |
| `page` | `profile`, `page` |
| `profile` | `profile`, `page` |
| `agent` | `agent`, `action` |
| `command` | `plugin`, `command`, `args`. Only the plugin it is addressed to receives it. |

A key triggers a plugin with this action:

```json
{"type": "plugin", "plugin": "my-plugin", "command": "reset", "args": {}}
```

`command` is 1 to 64 letters, digits, dots, dashes or underscores. `args` is an object of at most 1,024 characters as JSON.

## Compatibility

This is Tessera's own, versioned interface (`api: 1`). It is not the Stream Deck SDK and it is not OpenAction or OpenDeck compatible. No compatibility is claimed because none has been built or tested.
