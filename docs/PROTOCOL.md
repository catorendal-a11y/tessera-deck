# Serial protocol

[Back to the README](../README.md)

The host and the panel talk over USB Serial/JTAG at 115200 baud. This page lists every line they exchange. The source is `main/main.cpp` and `main/deck_model.c` on the panel, `host/panel_serial.py` and `host/tesserad.py` on the host. The current protocol is version 4; [Releasing](RELEASING.md) lists what each version added.

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
| `AD_TIME YYYY-MM-DDTHH:MM:SS [12h\|24h]` | `AD_TIME OK` or `INVALID` | The PC's local time, sent every 10 minutes and when the clock format changes. The panel has no network clock. The optional format sets 12- or 24-hour clocks; firmware before 0.8.1 ignores it. |
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
| `{"type":"info","boardId":"tessera-p4","firmwareVersion":"…","protocol":4,"bootId":N,"uptime":N,"heap":N,"psramFree":N,"reset":"…","ota":1,"layoutSaved":N}` | The answer to `get_info` | Accepts only `tessera-p4` and a supported protocol. See [Handshake fields](#handshake-fields). |
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

### Handshake fields

| Field | Meaning |
|---|---|
| `boardId`, `firmwareVersion`, `protocol` | Identify the panel. The protocol number is the panel's own. |
| `bootId`, `uptime` | A new `bootId` tells the host the panel restarted. `uptime` is in seconds. |
| `heap`, `psramFree` | Free internal and external memory in bytes. |
| `reset` | Why the panel last started: `poweron`, `sw`, `panic`, `int_wdt`, `task_wdt`, `wdt`, `brownout`, `deepsleep`, `ext` or `unknown`. The host warns about `panic`, `int_wdt`, `task_wdt`, `wdt` and `brownout`. |
| `ota` | `1` when the panel accepts `AD_OTA_*`. Missing on older firmware. |
| `layoutSaved` | Unix time of the saved offline layout, 0 when unknown. Missing on older firmware. |

A pressed key stays highlighted until the host answers with `AD_FEEDBACK`. Without a host it flashes red at once.

## Firmware update

The update writes the new image into the idle A/B slot (needs `"ota":1`). Every step is answered `<command> OK` or `<command> FAIL <reason>`.

1. `AD_OTA_BEGIN <bytes> <sha256>` opens the slot. Failures: `usage`, `no_slot`, `too_big`, `begin`, `hash`.
2. `AD_OTA_DATA <offset> <hex>` sends at most 512 bytes a line, in order. The panel answers `AD_OTA_DATA OK <bytes received>` every 2 KB and at the end. Failures: `not_started`, `usage`, `offset`, `data`, `too_long`, `write`. Any failure ends the update.
3. `AD_OTA_END` checks the whole image. It answers `OK` or fails with `incomplete`, `checksum`, `invalid_image` or `boot_slot`.
4. After `AD_OTA_END OK` the panel restarts into the new slot. It keeps that slot once the host completes a handshake, or after 60 s. Otherwise the bootloader goes back to the previous slot.

`AD_OTA_ABORT` cancels an update and answers `AD_OTA_ABORT OK`. The slots and the install options are in [Releasing](RELEASING.md).

## Panel lock

`AD_PANEL_LOCK 1` makes the panel ignore touches on keys and rail and shows a lock badge in the header. A 2 s hold on the badge unlocks it and sends `{"type":"unlocked"}`. A panel that restarts boots unlocked, so the host sends `AD_PANEL_LOCK 1` again after a reconnect when the lock was on.

## Confirm keys

A key with `"cf":1` sends its press only after the finger stays down for 600 ms. A ring fills meanwhile, so a brush does nothing. The editor sets this with *Hold to confirm* on the Actions tab.
