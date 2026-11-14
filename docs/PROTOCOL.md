# Serial protocol

[Back to the README](../README.md)

The host and the panel talk over USB Serial/JTAG at 115200 baud. This page lists every line they exchange. The source is `main/main.cpp` and `main/deck_model.c` on the panel, `host/panel_serial.py` and `host/tesserad.py` on the host. The current protocol is version 5; [Releasing](RELEASING.md) lists what each version added.

## Framing

- Each message is one UTF-8 line ending in `\n`.
- The panel reads lines of up to 1,099 bytes and ignores a longer one without an answer. The host therefore sends a layout in chunks of 380 characters, an image in chunks of 160 bytes and a firmware image in chunks of 512 bytes (both hex-encoded).
- The host sends commands as `AD_…` text lines (the prefix is historical and stays for compatibility) or as one JSON object, `{"cmd":"get_info"}`.
- The panel answers every command except the ones marked *no answer* below. A layout, an image and a firmware update are answered once, at their `…_END` line.
- The panel sends its own events as JSON lines. The host ignores any line it does not know.
- Any complete line from the host counts as a sign of life. `AD_PING` has no other job.

## Host to panel

| Message | Answer | What it does |
|---|---|---|
| `{"cmd":"get_info"}` | `{"type":"info",…}` (table below) | The handshake. The host refuses another board or a protocol it does not support. |
| `AD_PING` | none | Heartbeat every second. The rail shows *NO PC* after 3.5 s without any line from the host. |
| `AD_TIME YYYY-MM-DDTHH:MM:SS [12h\|24h]` | `AD_TIME OK` or `INVALID` | The PC's local time, sent every 10 minutes and when the clock format changes. The panel has no network clock. The optional format sets 12- or 24-hour clocks; older firmware ignores it. |
| `AD_CFG_BEGIN`, `AD_CFG_DATA <chunk>`, `AD_CFG_END` | `AD_CFG_BEGIN OK`, none, then `AD_CFG_END OK <keys>`, `INVALID` or `TOO_BIG 8192` | Pushes the key layout (JSON, chunked). See [Layout](#layout). |
| `AD_IMG_BEGIN <id> <bytes> <crc32>`, `AD_IMG_DATA <offset> <hex>`, `AD_IMG_END` | only at the end: `AD_IMG_END OK <id>`, `INVALID` or `FULL` | Uploads a key image. `FULL` means the 8 MiB image cache cannot hold it. |
| `AD_CONTEXT {"profile":"…","page":"…","canBack":true}` | `AD_CONTEXT OK` or `INVALID` | Profile, page and back state for the header. |
| `AD_FEEDBACK ok <id>` or `AD_FEEDBACK alert <id>` | `AD_FEEDBACK OK` or `INVALID` | Ends the pressed highlight with a green or red flash. |
| `AD_BRIGHTNESS <1-100>` | `AD_BRIGHTNESS OK <level>`, `FAILED <level>` or `INVALID` | Sets the backlight and stores the level on the panel. |
| `AD_DISPLAY_DIM <0-100>` | `AD_DISPLAY_DIM OK <level>`, `FAILED <level>` or `INVALID` | Dims the backlight without changing the stored level. |
| `AD_DISPLAY_WAKE` | `AD_DISPLAY_WAKE <esp error name> QUEUED` or `NO_REDRAW` | Restores the stored backlight and redraws. |
| `AD_PANEL_LOCK 1` or `AD_PANEL_LOCK 0` | `AD_PANEL_LOCK OK <1 or 0>` | Locks or unlocks the touch screen. See [Panel lock](#panel-lock). |
| `AD_SCREEN deck` or `AD_SCREEN ambient` | `{"type":"screen","queued":true}` | Shows the keys or the ambient clock (protocol 3). |
| `AD_AMBIENT <text>` | `AD_AMBIENT OK` | The line under the ambient clock, for example the weather (protocol 3). |
| `AD_AGENTS {"agents":[…]}` | `AD_AGENTS OK` or `INVALID` | The agents screen, up to 3 lanes (protocol 4). |
| `AD_MIXER {"faders":[…]}` | `AD_MIXER OK` or `INVALID` | The mixer screen, up to 5 faders (protocol 4). |
| `AD_STATS {"stats":[…]}` | `AD_STATS OK` or `INVALID` | The status screen, up to 8 readings (protocol 4). |
| `AD_RAIL {"rail":[…]}` | `AD_RAIL OK` or `INVALID` | The rail's buttons, at most 7 (protocol 4). |
| `AD_VIEW keys`, `agents`, `mixer` or `status` | `AD_VIEW OK` or `INVALID` | Brings one screen forward, for example for a permission question (protocol 4). |
| `AD_OTA_BEGIN <bytes> <sha256>`, `AD_OTA_DATA <offset> <hex>`, `AD_OTA_END`, `AD_OTA_ABORT` | see [Firmware update](#firmware-update) | Updates the firmware over USB. |
| `AD_WIFI_SET {"ssid":"…","password":"…"}` | `AD_WIFI_SET OK`, `AD_WIFI_SET INVALID json\|ssid\|password` or `AD_WIFI_SET FAILED storage` | Stores the Wi-Fi network and connects (protocol 5). See [Wi-Fi](#wi-fi). |
| `AD_WIFI_CLEAR` | `AD_WIFI_CLEAR OK` or `AD_WIFI_CLEAR FAILED storage` | Forgets the network and turns Wi-Fi off (protocol 5). |
| `AD_WIFI_STATUS` | one `{"type":"wifi",…}` line | Asks for the Wi-Fi state (protocol 5). |
| `AD_API_SET {"enabled":true,"name":"tessera-deck","friendly":"Tessera Deck","area":""}` | `AD_API_SET OK`, `AD_API_SET INVALID json\|enabled\|name\|friendly\|area` or `AD_API_SET FAILED storage` | Turns the Home Assistant API on or off and names the device (`"api":1`). See [Home Assistant](#home-assistant). |
| `AD_API_KEY` | `AD_API_KEY <44 characters of base64>` or `AD_API_KEY FAILED storage` | The encryption key for Home Assistant; made on the panel if there is none (`"api":1`). |
| `AD_API_KEY NEW` | the same | Makes a new key and closes every API connection (`"api":1`). |
| `AD_API_OPTIONS {"profiles":["…"],"pages":["…"]}` | `AD_API_OPTIONS OK` or `AD_API_OPTIONS INVALID` | The names for the Profile and Page selects: at most 16 each, 1 to 31 bytes (`"api":1`). |
| `AD_API_STATUS` | one `{"type":"api",…}` line | Asks for the API state and the pairing (`"api":1`). |
| `AD_PRESS <id>` | `AD_PRESS OK` or `UNKNOWN` | A synthetic key press. Only `tests/hardware_smoke.py` uses it. |
| `FQ_UI_STATUS` | `FQ_UI_STATUS {"screen":N,"labels":"…"}` | A debug dump of the visible text. The host never sends it. |

### Layout

`AD_CFG_END` takes one JSON object, `{"buttons":[…]}`, of up to 18 keys and 8,192 bytes. A bigger layout is answered `TOO_BIG 8192`. The host sends the layout once more if the panel does not answer within 4 s.

Each key needs `id` (1 to 18, no duplicates) and a non-empty `label`. The other fields are optional:

| Field | Meaning |
|---|---|
| `icon`, `color` | Icon name (`ok` when missing) and accent color as hex. |
| `bg`, `text_color`, `border` | Color overrides as hex. |
| `title` | `{"size":16\|20\|24\|28,"position":"top"\|"middle"\|"bottom"\|"hidden","bold":true}`. |
| `gauge` | `{"p":0-100,"t":"text","b":"badge icon"}`, a percentage on the key. |
| `hold`, `double` | `true` when the key has a long-press or double-press action. |
| `cf` | `1` for a confirm key. See [Confirm keys](#confirm-keys). |
| `span` | 1 to 3: a wide key covering that many slots to the right (protocol 4). |
| `sub`, `progress`, `ring` | A second line, a progress bar from 0 to 100, and `true` to draw the progress as a ring (protocol 4). The host fills these for music, timers and every widget, so a new widget needs no new firmware. |
| `ha` | Home Assistant steps the panel runs itself (`"ha":1`). See [Home Assistant keys](#home-assistant-keys). |
| `hs` | A Home Assistant entity the key follows (`"ha":1`). See [Home Assistant keys](#home-assistant-keys). |

An invalid key makes the whole layout `INVALID`. A valid layout is saved on the panel after a short delay, so the panel shows its keys without the PC. The panel keeps the previous layout as a backup (`/store/layout.json` and `layout.bak`). Firmware from before the A/B layout kept only 3,800 bytes.

### Screens

Each list is a JSON object with one array. Text fields are shortened to fit; ids are limited to 39 safe characters.

| Message | Array entries |
|---|---|
| `AD_AGENTS` | `id`, `name` (needed), `state` (`idle`, `working` or `waiting`), `text`, `sub`, `q` (`1` when the lane asks a question). |
| `AD_MIXER` | `id` (the host's audio target), `name`, `level` (0-100), `muted`, `mic`, `color`. |
| `AD_STATS` | `name`, `value`, `unit`, `p` (0-100), `color`, `warn`. |
| `AD_RAIL` | `k` is `keys`, `agents`, `mixer`, `status`, `page` or `act`. A `page` entry also needs `p` (profile) and `g` (page) and may carry `i` (icon). An `act` entry (firmware 0.6.3) carries only `i`. |

A color is a hex string. A wrong color, an unknown `k` or a missing name makes the whole message `INVALID`.

## Panel to host

| Message | When | What the host does |
|---|---|---|
| `{"type":"info","boardId":"tessera-p4","firmwareVersion":"…","protocol":5,"bootId":N,"uptime":N,"heap":N,"psramFree":N,"reset":"…","ota":1,"wifi":"off","layoutSaved":N}` | The answer to `get_info` | Accepts only `tessera-p4` and a supported protocol. See [Handshake fields](#handshake-fields). |
| `{"type":"deck_event","id":N,"button":N,"label":"…","hold":true}` | A key was pressed. `hold` is present for a long press. | Runs the key's actions. |
| `{"type":"wake"}` | A touch woke the dimmed panel. | Resets the idle timer. No key is pressed. |
| `{"type":"brightness","level":N}` | The brightness slider was released. | Stores the level (1 to 100). |
| `{"type":"screen","name":"deck","by":"touch"}` | A touch left the ambient screen (protocol 3). | Stops showing the ambient clock. |
| `{"type":"view","v":N}` | The rail opened a screen: 0 keys, 1 agents, 2 mixer, 3 status. | Counts the tap as activity and reads the sound devices when the mixer opens. |
| `{"type":"rail","i":N}` | Rail button N was touched. | Switches to the page shortcut or runs the steps of an `act` shortcut. |
| `{"type":"agent","id":"claude","do":"allow\|deny\|stop\|open"}` | A lane button was touched. | Answers the question, stops the agent or opens its window. |
| `{"type":"fader","id":"…","level":0-100}` | A fader was dragged. | Sets that audio target's volume. |
| `{"type":"mute","id":"…"}` | A mute button was touched. | Toggles mute. |
| `{"type":"image","id":"im:…"}` | The panel needs an image it no longer has. | Sends the image again. |
| `{"type":"unlocked"}` | The lock badge was held for 2 s. | Marks the panel as unlocked. |
| `{"type":"wifi","state":"…",…}` | The answer to `AD_WIFI_STATUS`, and on its own when the Wi-Fi state changes (protocol 5). | Shows the state in the editor. See [Wi-Fi](#wi-fi). |
| `{"type":"api","enabled":true,"clients":1,"ha":true,"name":"tessera-deck"}` | The answer to `AD_API_STATUS`, and on its own when it changes (at most one a second). | `ha` is true while a client has subscribed to the states. |
| `{"type":"ha_select","what":"profile"\|"page","value":"…"}` | Home Assistant picked a profile or page in its select. Sent only while the PC is linked and the value is one of `AD_API_OPTIONS`. | Validates it and switches, as a rail shortcut does. |

### Handshake fields

| Field | Meaning |
|---|---|
| `boardId`, `firmwareVersion`, `protocol` | Identify the panel. The protocol number is the panel's own. |
| `bootId`, `uptime` | A new `bootId` tells the host the panel restarted. `uptime` is in seconds. |
| `heap`, `psramFree` | Free internal and external memory in bytes. |
| `reset` | Why the panel last started: `poweron`, `sw`, `panic`, `int_wdt`, `task_wdt`, `wdt`, `brownout`, `deepsleep`, `ext` or `unknown`. The host warns about `panic`, `int_wdt`, `task_wdt`, `wdt` and `brownout`. |
| `ota` | `1` when the panel accepts `AD_OTA_*`. Missing on older firmware. |
| `layoutSaved` | Unix time of the saved offline layout, 0 when unknown. Missing on older firmware. |
| `wifi` | `off`, `connecting`, `connected` or `failed` (protocol 5). With the protocol number it tells the host that `AD_WIFI_*` exists. |
| `api` | `1` when the panel has the Home Assistant API and accepts `AD_API_*`. Missing on older firmware. |
| `ha` | `1` when the panel reads the layout's `ha` and `hs` key fields and runs Home Assistant steps itself. Missing on older firmware: the host strips those fields and runs no Home Assistant step. |

A pressed key stays highlighted until the host answers with `AD_FEEDBACK`. Without a host it flashes red at once. A key with Home Assistant steps for that trigger follows Home Assistant instead (see [Home Assistant keys](#home-assistant-keys)).

## Firmware update

The update writes the new image into the idle A/B slot (needs `"ota":1`). Every step is answered `<command> OK` or `<command> FAIL <reason>`.

1. `AD_OTA_BEGIN <bytes> <sha256>` opens the slot. Failures: `usage`, `no_slot`, `too_big`, `begin`, `hash`.
2. `AD_OTA_DATA <offset> <hex>` sends at most 512 bytes a line, in order. The panel answers `AD_OTA_DATA OK <bytes received>` every 2 KB and at the end. Failures: `not_started`, `usage`, `offset`, `data`, `too_long`, `write`. Any failure ends the update.
3. `AD_OTA_END` checks the whole image. It answers `OK` or fails with `incomplete`, `checksum`, `invalid_image` or `boot_slot`.
4. After `AD_OTA_END OK` the panel restarts into the new slot. It keeps that slot once the host completes a handshake, or after 60 s. Otherwise the bootloader goes back to the previous slot.

`AD_OTA_ABORT` cancels an update and answers `AD_OTA_ABORT OK`. The slots and the install options are in [Releasing](RELEASING.md).

## Wi-Fi

Protocol 5. The panel joins Wi-Fi through its ESP32-C6. Wi-Fi is off until `AD_WIFI_SET` stores a network: before that the panel never starts the C6, and USB works exactly as without Wi-Fi.

- `AD_WIFI_SET` takes exactly one space and then the JSON on the rest of the line; the whole line is at most 1,099 bytes, and a longer one is dropped without an answer. `ssid` is 1 to 32 bytes of UTF-8 after JSON decoding, without control characters. `password` is `""` for an open network, 8 to 63 printable ASCII characters, or exactly 64 hex digits. Other keys are ignored. The host sends `json.dumps(…, ensure_ascii=True, separators=(',', ':'))`, so the line is pure ASCII.
- `INVALID` names the first field that failed: `json` (not an object, or a `\u0000` escape), `ssid` or `password`. `OK` means stored and connecting, not connected; the result arrives as `{"type":"wifi"}` lines. `FAILED storage` means the settings could not be written.
- The panel keeps the network in NVS (namespace `tessera_net`) and never on the C6. No answer and no log line carries the password; the panel zeroes the line after `AD_WIFI_SET`.
- `AD_WIFI_CLEAR` erases the stored network (`ssid`, `pass`, `boot_guard` in `tessera_net`) and stops Wi-Fi. The Home Assistant settings and key stay.

The status line:

```json
{"type":"wifi","state":"connected","ssid":"HomeNet","ip":"192.168.1.40","rssi":-58,"mac":"AA:BB:CC:DD:EE:FF","cp":"2.7.0"}
{"type":"wifi","state":"failed","reason":"auth","ssid":"HomeNet"}
{"type":"wifi","state":"off"}
```

`state` is always there. `ssid` appears when a network is stored, `ip` and `rssi` only when `connected`, `reason` only when there is one, and `mac` and `cp` (the C6's ESP-Hosted version) once known. The panel sends the line on its own when the state, reason, SSID or address changes, at most once a second; a new signal strength alone sends nothing.

| `reason` | Meaning |
|---|---|
| `no_coprocessor` | The C6 did not answer within 15 s. The panel leaves it alone until the next `AD_WIFI_SET` or a restart. |
| `init` | The network stack could not start. |
| `no_ap` | The network was not found three times in a row. Tries again every minute. |
| `auth` | The password was refused three times in a row. Tries again every 5 minutes. |
| `no_ip` | No address from DHCP within 30 s. Tries again with backoff. |
| `lost` | Was connected; reconnecting (state `connecting`). Retries after 2, 4, 8, 16, 32, then every 60 s. |
| `crashed` | The last Wi-Fi start crashed the panel, so Wi-Fi stays off until the next `AD_WIFI_SET`. |
| `storage` | The settings could not be read. |

Stages B and C (Home Assistant) add the capability fields `"api":1` and `"ha":1` to `get_info`, not a new protocol number.

## Home Assistant

Capability `"api":1`. The panel runs an ESPHome-compatible native API server on TCP 6053, so Home Assistant finds it over mDNS (`_esphomelib._tcp`) and adds it with the encryption key. It is off until `AD_API_SET` turns it on, and it runs only while Wi-Fi is connected: with Wi-Fi off there is no socket, no mDNS and no crypto. USB works as before.

- Noise only (`Noise_NNpsk0_25519_ChaChaPoly_SHA256`). A plaintext client gets the reject frame `Bad indicator byte` and a close; a wrong key gets `Handshake MAC failure`. At most 4 clients; when all are busy a new client is refused, unless it replaces a pending connection from its own address or one that has been silent for 30 s. The handshake and `HelloRequest` must finish within 10 s. When the `AD_API_OPTIONS` lists change after a client listed the entities, the panel waits a second, sends `DisconnectRequest`, and the client reconnects and lists the new options.
- The key is 32 random bytes made on the panel (NVS `tessera_net/api_psk`). It leaves the panel only as the answer to `AD_API_KEY` over USB.
- The settings are in `tessera_net` as `api_on`, `api_name`, `api_friendly` and `api_area`. `name` is `^[a-z0-9-]{1,31}$` and is also the DHCP and mDNS hostname; `friendly` is 1 to 60 characters, `area` 0 to 40. `AD_WIFI_CLEAR` leaves them and the key alone.
- Entities: `key_1` … `key_18` (events `press`, `hold`, `double`), the `profile` and `page` selects, the `backlight` light, the `wifi_signal` sensor, the `pc_connected` binary sensor and the `show_clock` button. No entity can press a key or run a PC action.
- The About sheet shows `Home Assistant: off` (API turned off), `waiting` (on, no client subscribed) or `connected`.

### Home Assistant keys

Capability `"ha":1` (needs `"api":1`). The host sends these key fields only to such a panel:

```json
{"id":3,"label":"Kitchen","ha":{"p":[{"a":"light.toggle","e":"light.kitchen","d":{"brightness_pct":"50"}}],"h":[],"d":[]},
 "hs":{"e":"light.kitchen","a":"","m":"a","on":["on"],"u":""}}
```

| Field | Rules |
|---|---|
| `ha.p`, `ha.h`, `ha.d` | The steps for a press, a hold and a double press: at most 2 each, at most 24 in a layout. |
| step `a` | The action, `^[a-z_][a-z0-9_]*\.[a-z0-9_]+$`, at most 64 characters. Needed. |
| step `e` | Optional: one entity id or up to 4 comma-separated ids of the same form, at most 128 characters. Sent as the `entity_id` data entry. |
| step `d` | Optional: at most 4 pairs. Keys `^[a-z0-9_]{1,32}$` (not `entity_id`, which is `e`), values strings, numbers or booleans of at most 64 characters, sent as text (`true`/`false`). |
| `hs.e` | The followed entity: one id, as above. Needed. |
| `hs.a` | Optional attribute, `^[a-z0-9_]{0,32}$`; `""` follows the state. |
| `hs.m` | `a` (default): the key's color when the state is in `on`, else gray `#5A6270`. `v`: the state and `u` as the second line of a wide key, or as the label of a 1-slot key. `b`: both. |
| `hs.on` | 1 to 4 strings of at most 16 characters; default `["on"]`. |
| `hs.u` | Optional unit, at most 6 characters. |

A bad `ha` or `hs` makes the whole layout `INVALID`, as other key fields do. Unknown keys inside them are ignored; older firmware ignores both fields. The 8,192-byte limit holds, and the deepest field (`d`) is 7 levels down, inside the panel's cJSON limit of 16. The fields are saved with the layout, so HA keys work after a restart without the PC.

- **Who runs the steps:** always the panel, PC or not. It sends one `HomeassistantActionRequest` (35) per step to every client that sent `SubscribeHomeassistantServicesRequest` (34). The host skips `homeassistant` steps, and sends no `AD_FEEDBACK` for a trigger with only such steps, so nothing runs twice.
- **Feedback:** while Home Assistant is connected the key pulses and then flashes green when every step was delivered to a subscribed client (HA sends no answer, so green means delivered, not done). It flashes red at once without Home Assistant, and red when no client subscribed to actions. Home Assistant must allow the device to perform actions (ESPHome integration options).
- **Following:** after `SubscribeHomeAssistantStatesRequest` (38) the panel sends one `SubscribeHomeAssistantStateResponse` (39) per distinct entity/attribute pair, and again when the layout's pairs change. Each `HomeAssistantStateResponse` (40) changes the key's color and text in place; a state is cut to 63 bytes. Without a state the key looks as the host sent it. When Home Assistant leaves, the states stay, drawn faded. Past 72 subscriptions on one connection the panel sends `DisconnectRequest` so the client starts clean.

## Panel lock

`AD_PANEL_LOCK 1` makes the panel ignore touches on keys and rail and shows a lock badge in the header. A 2 s hold on the badge unlocks it and sends `{"type":"unlocked"}`. A panel that restarts boots unlocked, so the host sends `AD_PANEL_LOCK 1` again after a reconnect when the lock was on.

## Confirm keys

A key with `"cf":1` sends its press only after the finger stays down for 600 ms. A ring fills meanwhile, so a brush does nothing. The editor sets this with *Hold to confirm* on the Actions tab.
