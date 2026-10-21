# Writing a Tessera plugin

A plugin is a small program that adds values, key states and actions to Tessera. It runs as its own process,
talks to Tessera over the local control API and can be written in any language.

> **Trust.** A plugin runs with your own Windows rights; Tessera does **not** sandbox it. The limits below stop a
> plugin from using Tessera's API beyond what it declared, they do not stop it from doing anything else on your PC.
> Only install plugins you trust.

## Layout

```text
plugins/
  my-plugin/
    plugin.json     the manifest
    main.py         your program (any language; see "command")
```

`plugins/example-uptime` is a complete, working example that uses only the Python standard library.

## The manifest

```json
{
  "id": "my-plugin",
  "name": "My plugin",
  "version": "1.0.0",
  "api": 1,
  "command": ["python", "main.py"],
  "permissions": ["vars", "events"],
  "settings": {
    "interval": { "type": "number", "label": "Seconds between updates", "default": 5 }
  }
}
```

| Field | Rules |
|---|---|
| `id` | 2–32 lowercase letters, digits or dashes; must equal the folder name |
| `api` | must be `1` |
| `command` | the program and its arguments, no shell. `python` means Tessera's own interpreter; anything else must be a file inside the plugin folder |
| `permissions` | any of `vars`, `press`, `feedback`, `state`, `events`, `read` (below) |
| `settings` | up to 20 options of type `text`, `number` or `checkbox`; the editor shows them in **Plugins …** |

Turn a plugin on in the editor (**⋯ → Plugins …**) or in `profiles.json`:
`"plugins": { "my-plugin": { "enabled": true, "settings": { "interval": 10 } } }`.

## What your program receives

Environment variables (nothing else from your environment is passed on except basic Windows paths):

| Variable | Meaning |
|---|---|
| `TESSERA_API` | base URL of the local API, for example `http://127.0.0.1:50321` |
| `TESSERA_TOKEN` | your own token, sent as the `X-Deck-Token` header |
| `TESSERA_PLUGIN` | your id |
| `TESSERA_SETTINGS` | the settings as JSON |

Output goes to `host/plugins/<id>.log`. Tessera restarts a plugin that stops, waiting 1, 2, 4 … up to 60 seconds,
and gives up after five quick crashes until the plugin is turned off and on again. Changing a plugin's settings
restarts it.

## Permissions

| Permission | Allows |
|---|---|
| `vars` | `POST /v1/var` and `POST /v1/vars` — **only for names starting with `<id>.`** |
| `press` | `POST /v1/press` — press a key |
| `feedback` | `POST /v1/feedback` — flash a key green or red |
| `state` | `POST /v1/state` — set a toggle key's state |
| `events` | `GET /v1/events` — read key presses, page changes and commands for this plugin |
| `read` | `GET /v1/state` — read the host state |

A request outside the permissions gets `403` and nothing is queued. A full queue answers `503` with
`"retry": true`; try again shortly.

## Showing values and changing keys

Set a variable and use it in a key name: `POST /v1/vars` with `{"set": {"my-plugin.text": "42"}}`, then name a key
`$(var:my-plugin.text)`. Colors follow a variable with the key's `status` setting, and a toggle key can be driven
with the `state` route.

## Reacting to keys: events

`GET /v1/events?since=<last id>&wait=<seconds, at most 25>` returns
`{"events": [...], "last": <id>}`. Pass the returned `last` as the next `since`. It waits up to `wait` seconds for
news, so one loop is enough. Event types:

| `type` | Fields |
|---|---|
| `press` | `button`, `label`, `profile`, `page`, `ok`, `hold` |
| `page` | `profile`, `page` |
| `profile` | `profile`, `page` |
| `command` | `plugin`, `command`, `args` — only delivered to the plugin it is addressed to |

A key triggers a plugin with the action `{"type": "plugin", "plugin": "my-plugin", "command": "reset", "args": {}}`.
`command` is 1–64 letters, digits, dots, dashes or underscores; `args` is a small object.

## Compatibility

This is Tessera's own, versioned interface (`api: 1`). It is **not** the Stream Deck SDK and it is **not**
OpenAction/OpenDeck compatible; no compatibility is claimed because none has been built or tested.
