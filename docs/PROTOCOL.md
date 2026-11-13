# Serial protocol

[Back to the README](../README.md)

115200 baud over USB Serial/JTAG. Lines are UTF-8; the panel answers every command except `AD_PING`, `AD_CFG_DATA`, `AD_IMG_BEGIN` and `AD_IMG_DATA`: a layout or an image is answered once, at its `…_END`.

| Direction | Message | Purpose |
|---|---|---|
| host → panel | `{"cmd":"get_info"}` | Board id (`tessera-p4`), firmware, boot id, memory |
| host → panel | `AD_CFG_BEGIN` / `AD_CFG_DATA …` / `AD_CFG_END` | Push the button layout (JSON, chunked) |
| host → panel | `AD_IMG_BEGIN` / `AD_IMG_DATA` / `AD_IMG_END` | Upload a button image (CRC-checked) |
| host → panel | `AD_CONTEXT {…}` | Profile, page and back-arrow state for the header |
| host → panel | `AD_FEEDBACK <ok or alert> <id>` | Flash a key green or red |
| host → panel | `AD_BRIGHTNESS <1-100>`, `AD_DISPLAY_DIM <0-100>`, `AD_DISPLAY_WAKE` | Backlight control; the brightness is stored on the panel |
| host → panel | `AD_PRESS <id>` | A synthetic key press, used by `tests/hardware_smoke.py`; answers `AD_PRESS OK` or `UNKNOWN` |
| host → panel | `AD_PING` | Heartbeat every second; the rail shows *NO PC* after 3.5 s without one |
| host → panel | `AD_TIME YYYY-MM-DDTHH:MM:SS` | The PC's local time for the clock on the rail and the ambient clock; the panel has no network clock |
| host → panel | `AD_SCREEN deck` / `AD_SCREEN ambient` | Show the keys or the ambient clock (protocol 3) |
| host → panel | key fields `span` (1-3), `sub`, `progress` (0-100), `ring` | A wide key in the layout the host pushes: it covers `span` slots to the right and shows a title, a second line and a progress bar or ring (protocol 4). The host fills these for music, timers and every widget, so a new widget needs no new firmware |
| host → panel | `AD_AGENTS {"agents":[{id,name,state,text,sub}]}` | The agents screen: up to 3 lanes, `state` is idle, working or waiting (protocol 4) |
| host → panel | `AD_MIXER {"faders":[{id,name,level,muted,mic,color}]}` | The mixer screen: up to 5 faders; `id` is the host's audio target (protocol 4) |
| host → panel | `AD_STATS {"stats":[{name,value,unit,p,color,warn}]}` | The status screen: up to 8 readings (protocol 4) |
| host → panel | `AD_VIEW keys\|agents\|mixer\|status` | Bring one of the four screens forward, for example for a permission question (protocol 4) |
| panel → host | `{"type":"agent","id":"claude","do":"allow\|deny\|stop\|open"}` | A lane button was touched (protocol 4) |
| panel → host | `{"type":"fader","id":"…","level":0-100}` / `{"type":"mute","id":"…"}` | A fader was dragged or a mute button touched (protocol 4) |
| host → panel | `AD_RAIL {"rail":[{"k":"keys"},{"k":"page","i":"lc:e0e8","p":"Chrome","g":"main"}]}` | The rail's buttons, at most 7: `k` is keys, agents, mixer, status, page or act; a page shortcut carries its icon, profile and page, an `act` shortcut (firmware 0.6.3) only its icon: a tap sends `rail` and the host runs the steps (protocol 4) |
| panel → host | `{"type":"rail","i":N}` | Rail button N, a page shortcut, was touched; the host switches to that page (protocol 4) |
| host → panel | `AD_AMBIENT <text>` | The line under the ambient clock, for example the weather (protocol 3) |
| panel → host | `{"type":"info","boardId":"tessera-p4","firmwareVersion":…,"protocol":4,…}` | The answer to `get_info`; the host refuses another board or an unsupported protocol. Newer firmware adds `reset` (why it last started: poweron, sw, panic, int_wdt, task_wdt, wdt, brownout, deepsleep, ext or unknown), `"ota":1` (it accepts `AD_OTA_*`) and `layoutSaved` (Unix time of the offline layout, 0 when unknown) |
| host → panel | `AD_OTA_BEGIN <size> <sha256>` / `AD_OTA_DATA <offset> <hex>` / `AD_OTA_END` | Firmware update over USB into the idle A/B slot (`"ota":1`). Each step answers `… OK` or `… FAIL <reason>`; data goes in order, at most 512 bytes a line, and is answered `AD_OTA_DATA OK <bytes>` every 2 KB. After `AD_OTA_END OK` the panel restarts into the new slot, which it confirms once the host completes a handshake (or after 60 s); otherwise the bootloader goes back to the previous one |
| panel → host | `{"type":"deck_event","id":N,"button":N,"label":"…","hold":true}` | A key was pressed (`hold` for a long press, protocol 2) |
| panel → host | `{"type":"wake"}` | A touch woke the dimmed panel; it presses no key |
| panel → host | `{"type":"screen","name":"deck","by":"touch"}` | A touch left the ambient screen (protocol 3) |

Layout entries may also carry `hold` and `double` (the key has a long-press or double-press action), `title` (size, position, bold), `bg`, `text_color` and `border` colors, and `gauge` (`p` percent, `t` text, `b` badge icon).
A layout is limited to 8 KB and up to 18 keys; an image upload answers `AD_IMG_END OK <id>`, `INVALID` or `FULL`
(the 8 MiB image cache cannot hold it). A layout over 8 KB is answered `AD_CFG_END TOO_BIG 8192`. Every layout the panel accepts is kept for use without the PC (a file on the storage partition, with the previous one as a backup; firmware before the A/B layout kept only 3,800 bytes). Protocol versions are listed in [`docs/RELEASING.md`](RELEASING.md).

A pressed key stays highlighted until the host confirms it with `AD_FEEDBACK`. Without a host it flashes red at once.

The `AD_` prefix is the protocol's historical namespace and is kept for compatibility.
