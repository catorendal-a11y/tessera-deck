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
| `obs` | Switches scenes, shows, hides or toggles a source, starts and stops recording and streaming, pauses recording, saves the replay buffer, toggles the virtual camera, triggers the studio mode transition, mutes an input and steps its volume. Shows the scene and *ON* or *OFF* states in key names. Needs OBS's WebSocket server (Tools → WebSocket Server Settings). |

The top of each `main.py` lists the key actions and variable names it offers.

### OBS commands and variables

In the editor, add a *Plugin command* step, choose OBS Studio and type a command from the table, with its arguments as JSON, for example `{"name": "Gaming"}` for `scene`. **Page → Page from a template … → OBS** gives a page with Record, Stream, Pause, Save replay, Virtual cam, Transition and the current scene. In `profiles.json` a command is a `plugin` action with `"plugin": "obs"`. Names of scenes, sources and inputs must match OBS exactly and are at most 256 characters. A command with missing or invalid arguments does nothing.

| Command | Arguments | Effect |
|---|---|---|
| `scene` | `name` | Switches the program scene. |
| `record`, `stream` | none | Starts or stops recording or streaming. |
| `pause` | optional `mode`: `toggle` (default), `on` or `off` | Pauses or resumes recording. |
| `replay` | none | Saves the replay buffer. |
| `virtualcam` | none | Starts or stops the virtual camera. |
| `transition` | none | Runs the studio mode transition. |
| `mute` | `input` | Toggles an input's mute. |
| `source` | `source`, optional `scene` (default: the current scene), optional `mode`: `toggle` (default), `show` or `hide` | Enables or disables a source in a scene. |
| `volume-up`, `volume-down` | `input`, optional `step` in dB (default 2, above 0 up to 20) | Changes the input volume. The result stays between -100 and 26 dB. |

Variables: `obs.scene`, `obs.recording`, `obs.streaming` and `obs.paused` (*ON* or *OFF*), `obs.connected`, and `obs.error`. `obs.error` holds the reason when OBS refuses a command, for example when the replay buffer is not running, and is empty after the next command that works. It also reports a command OBS does not answer within five seconds, and a source key pressed before the current scene is known. Failures of the plugin's own startup requests are not reported there. When OBS disconnects, `obs.error` is cleared and the `obs.mute.*` variables become empty. Two quick volume presses add up, and a second toggle of the same source is ignored until the first has finished.

To follow mute state, list the inputs in the plugin's *Inputs whose mute state to show* setting, separated by commas (up to 10). Each one gets `obs.mute.<name>`, *ON* when muted, where characters other than letters, digits, dash and underscore in the name become underscores, so `Mic/Aux` is `obs.mute.Mic_Aux`. Use it in a key's `status` to colour a mute key. If two names give the same variable, such as `Mic/Aux` and `Mic_Aux`, the first one is kept and the others are ignored and noted in the plugin's log.

While OBS cannot be reached, a key flashes red and the panel shows why for three seconds, for example *OBS is not running*. The plugin asks for `notify` and `feedback` for this.

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
4. To restart the count from a key, give it a *Plugin command* step with the plugin *Example: uptime* and the command `reset`. The full example reads it as an event.

## The manifest

| Field | Rules |
|---|---|
| `id` | 2 to 32 lowercase letters, digits or dashes, starting with a letter. Must equal the folder name. |
| `name`, `version` | Text of 1 to 60 characters. |
| `api` | Must be `1`. |
| `command` | The program and its arguments (1 to 12 words), run without a shell. `python` means Tessera's own interpreter. Anything else must be a file inside the plugin folder. |
| `permissions` | Any of `vars`, `press`, `feedback`, `state`, `notify`, `events`, `read`. No duplicates. |
| `settings` | Up to 20 options. A key is lowercase letters, digits and underscores, starting with a letter (up to 32). `type` is `text`, `number` or `checkbox`; `label` and `default` are optional. The editor shows them in **Plugins …**. |

A folder with a bad manifest is skipped, and the editor shows the reason.

## Turning a plugin on

Turn it on in the editor, or in `profiles.json`:

```json
"plugins": { "my-plugin": { "enabled": true, "settings": { "interval": 10 } } }
```

- **Consent.** When you turn a plugin on, the editor lists what it may do and the program it runs, and asks first. It asks again only when the `version`, permissions or program changed since you said yes, and remembers your answer in the browser. A plugin that is already on gets what its manifest lists at its next start without asking, so read what an update changes before you install it. A profile file you import cannot turn plugins on or change their settings.
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
- A plugin that stops is started again after 1, 2, 4 and 8 seconds.
- After the fifth crash in a row it gives up and the editor shows the error. Turn the plugin off and on again, or change its settings, to start it again. A plugin that runs for 60 seconds counts as stable and its crash count starts from zero.
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
| `notify` | `POST /v1/notify` with `{"text": "Build passed", "level": "ok", "seconds": 6}` shows a short message on the panel. `text` is 1 to 100 characters on one line, `level` is `info` (default), `ok`, `warn` or `error`, and `seconds` is 1 to 30 (default 6). Without a panel that can show the banner (none connected, or older firmware), the message becomes a tray notification that follows the Show Windows notifications setting, and is otherwise dropped. |
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

`GET /v1/events?since=<last id>&wait=<seconds>` returns `{"events": [...], "last": <id>}`. Start with `since=0` or omit it, and pass the returned `last` as the next `since`. The request waits up to `wait` seconds (at most 25) for news, so one loop is enough. Tessera keeps the last 200 events and returns at most 100 at a time, oldest first. To react only to what happens after the plugin starts, ask again with `since=<last>` while a reply holds 100 events, then start from the `last` of the shorter reply. Every event also has `id`, `type` and `at` (Unix time).

| `type` | Fields |
|---|---|
| `press` | `button`, `label`, `profile`, `page`, `ok`, `hold`, `double` |
| `page` | `profile`, `page` |
| `profile` | `profile`, `page` |
| `agent` | `agent`, `action` |
| `command` | `plugin`, `command`, `args`, and `button` when a key sent it. Only the plugin it is addressed to receives it. |

A key triggers a plugin with this action:

```json
{"type": "plugin", "plugin": "my-plugin", "command": "reset", "args": {}}
```

`command` is 1 to 64 letters, digits, dots, dashes or underscores. `args` is an object of at most 1,024 characters as JSON.

In the editor this is the *Plugin command* step under Advanced. It lists the installed plugins and does not save a step that breaks these rules. A key with a `plugin` step fails and flashes red when that plugin is not installed, is turned off or has stopped. The reason shows in the editor, and on the panel when its firmware has the banner.

## Compatibility

This is Tessera's own, versioned interface (`api: 1`). It is not the Stream Deck SDK and it is not OpenAction or OpenDeck compatible. No compatibility is claimed because none has been built or tested.
