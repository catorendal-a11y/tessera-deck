# Changelog

## Unreleased

- New panel layout (firmware protocol 4): a rail with four screens. The keys keep their six-by-three deck; the agents, mixer and status screens are new.
- Agents: one lane per AI tool with its state and last message. Allow and Deny on the panel answer Claude Code's permission questions through a hook (`deckctl hooks claude-permission`); anything unclear falls back to Claude's own dialog.
- Mixer: drag faders for the speakers, up to three programs and the microphone; mute with a tap.
- Status: eight readings with bars, and the first one over its limit is named.
- Agents screen works without any setup: working and idle, the project and the last tool come from the session files Claude Code and Codex already write. **Connect Claude Code** (⋯ menu) adds the hooks for "waiting for you" and for answering permission questions on the panel; it keeps your other hooks and makes a backup.
- A Windows notice when an agent starts waiting for you or finishes more than a minute of work; the tray says who is waiting.
- The editor's status line shows the panel's firmware version and says when an update is available.
- Editor: a key's steps are listed in order ("1 Open program → 2 Hotkey"), hold and double-press steps show under it, the profile rules are explained in plain words, and a meter shows how much of the panel's offline memory the page uses.
- Fixed: a changed VERSION did not reach the firmware build, so a rebuilt panel could keep reporting the old version.
- Editor: a rail on the left with the panel's four screens. Keys is the editor you know; Agents, Mixer and Status show what the panel shows right now and let you choose what goes on them, with the Claude Code connection on the Agents screen.
- Wide keys: a key can cover 2 or 3 slots (Width in the key's settings) and show the music that plays (title, artist, progress bar) or a timer (time left in a ring). Needs the new firmware.
- The editor now looks like the panel: the same dark colors, flat rounded cards, mint/cyan/purple accents and a green accent line, instead of the grey Stream Deck look.
- The panel's rail is yours to choose: **Rail …** (⋯ menu) turns Agents, Mixer and Status on or off and adds up to three shortcuts to a page of any profile. The editor's rail follows the same choice. Needs the new firmware (at most seven buttons).
- Editor layout tidied: the title, the deck, the pages, the sync bar and the key's settings share one column and scroll together; the three settings sections stack instead of floating; the action library uses one icon family and no mismatched glyphs.
- Editor: **Panel screens** chooses the agents, mixer programs and readings.
- Editor: **Page templates** (⋯ menu) adds a ready-made page (Meetings, Coding, Media, Browser or empty) after showing how it will look.

## 0.5.2

- Fixed: a key that brings a running program to the front (for example Chrome) shrank a maximized window. Only a minimized window is restored now.
- The panel clock follows the PC in every time zone; it no longer applies Central European daylight-saving time on its own.
- The control API token file can only be read by the Windows account that runs Tessera.
- Triggers, timers, plugins and configuration reloads keep running while no panel is connected.
- Fixed: the host could stop when the USB cable dropped out at the moment the panel was dimmed (for example after sleep).
- Fixed: saving the configuration ran today's daily triggers a second time.
- Fixed: a trigger with a slow command, HTTP call or delay made the keys unresponsive until it finished. It now runs beside the keys; a trigger that is still running is skipped.
- Fixed: a firmware installation that hit an unexpected error stayed "running" forever.
- Fixed: stopping a plugin left the programs it had started running.
- The host log and plugin logs are rotated instead of growing without limit.

## 0.5.1

- Easier first start: `Tessera.cmd` installs Python with winget if it is missing and adds a Desktop shortcut, and the release zip includes the panel firmware.
- *Download firmware* is offered even when you already have the latest version, so a new panel can get it.
- The editor says when no panel answers.

## 0.5.0

- Fixed: in large windows the right-click menu of a key and the drag label appeared far from the pointer, and dialogs could reach past the screen edge. Only the main view scales with the window now.
- Fixed: on pages with live gauges a press or drag could lose its key when the editor refreshed the keys at that moment. The editor waits for the press to finish and leaves unchanged keys alone.
- Fixed: the *Lock profile* key only turned orange when the lock was on its long press.
- Fixed: *Settings* was hidden in windows narrower than 900 px, and the editor's hints still pointed at the old layout. A draft that cannot be saved now names the key.
- Fixed: a gauge without a unit (such as `301` or `LIVE`) sat slightly off centre on the panel.
- New action *Lock profile* (`profile_lock`): keeps the current profile while another program is in front; `$(profile_lock)` shows the state and the key turns orange while locked.
- New FPS gauge (`fps`) from HWiNFO's PresentMon sensor.
- Gauges say what they measure: `GHz`, `MHz`, `GB` and `rpm`. The size of a gauge's number now depends on the number alone, not on its unit.
- `$(pc:track)` shows *No music* when nothing is playing, so the music key is no longer blank.
- First-start fix: the editor creates `profiles.json` itself if it opens before the host. *Check for updates* says when nothing is published instead of blaming the network.
- `tools/render_screens.py` draws every page of every profile with the real panel UI into `build/screens`, without touching the panel.
- Faster status page: the host keeps one connection to Libre Hardware Monitor and lists the child processes of the window in front at most every 3 seconds, instead of both every second.

- Fixed: the VRAM, GPU load and CPU clock gauges blinked to "--" for one second every 15 seconds while the Windows counters were listed again; they now keep their last values meanwhile.
- GPU temperature, power, fan speed and clock now show without administrator rights or extra software: AMD cards through the driver's ADL library (checked on an RX 6950 XT), NVIDIA through `nvidia-smi`. Libre Hardware Monitor and HWiNFO still win when they run.
- `Tessera.cmd --sensors` registers a scheduled task that starts Libre Hardware Monitor at every sign-in with administrator rights (one Windows prompt), so the CPU temperature and power are always there; `--sensors-off` removes it. The editor's connection tooltip says what is missing when the CPU sensors are not available.

- Panel and editor: keys with a long-press action get a small ring in the top-right corner, keys with a double-press get two dots (layout field `double`, firmware `has_double`). The firmware builds with ESP-IDF 6.1 (1.93 MB) and the native LVGL test passes and renders the new marks; not yet flashed to a panel.

- New **Chrome** screen (profile): shown automatically when Chrome is in front. Main page: tabs, address bar, back/forward, refresh, find, bookmark, incognito, history, downloads and play/pause; a *Developer* folder with DevTools, inspect, console, view source, zoom, full screen, print, task manager and clear data. Home is pinned in slot 18. The *Browser* profile template now has the same keys (Chrome, Edge, Firefox) with proper icons.
- Editor: no sideways scrolling in windows narrower than 1280 px (the columns shrink and the key inspector moves under the deck below 1000 px); no more "undefined / undefined" when the panel has not reported its page yet.

- New action *Switch screen* (`screen`): show the clock, the keys, or switch between them, from any key. It works even when the idle clock is off; a touch on the clock returns to the keys.
- Quiet hours (`display.night`, in *Program settings*): between two times the panel uses a lower brightness, also across midnight, and returns to normal afterwards.

- Switching profiles by the program in front: Windows surfaces that only take focus for a moment (search, Start, notifications, Alt+Tab, the lock screen, taskbar) and Tessera's own windows no longer end or start an automatic switch; when the program loses focus you return to the page and folder you left, not the first page; Store (UWP) apps such as Calculator are recognised by their real program instead of `applicationframehost.exe`.

- USB reconnects wait 2, 5, then 10 seconds and log an outage once instead of every attempt; the panel layout is sent a second time if the first is not acknowledged; the heartbeat thread also ends quietly when the port disappears.
- The editor shows *too big to keep offline* when the page layout exceeds what the panel stores for use without the PC (3,800 bytes).
- The editor edits the full action list for normal, long and double press (tabs *Pressed / Held / Double-press*), replacing the hotkey-only fields.
- CI: ruff `B` rules, Python 3.12 and 3.14, host coverage gate (73 %). Terminal form said "Ja" instead of "Yes".
- Double press: `double_actions` on a key (editor field *Double-press hotkey*), checked, previewed and listed in import review like long press.
- HTTP actions only accept `http://` and `https://`, when the profile is saved and again after variables are filled in; the address may use `$(env:NAME)`.
- Variable substitution is a single pass: a value that looks like `$(other)` is no longer expanded a second time.
- Fixed: the Desktop shortcut (setup) and shortcut targets in the editor failed because PowerShell ignores `$args` with `-Command`.
- Panel: a layout that is too large for flash, or a failed flash write, is logged and retried instead of being marked as saved.

Firmware protocol 3, configuration version 2. Existing profiles load unchanged and are stamped with the new
version on the next save; the old file is kept in `host/backups`.

### Reliability and security

- The panel firmware no longer contains Wi-Fi, provisioning, SNTP or the ESP-Hosted stack; USB is the only
  transport (binary 2.43 MB → 1.92 MB). Not yet run on a physical panel.
- Verified device identity: the host asks `get_info` and checks the board id and protocol before it configures a
  port, tries other Espressif USB devices only after the remembered one, and discards key presses that arrive
  before the handshake.
- The action queue is bounded and reports a full queue (`503`) instead of dropping silently; multi-job requests
  are all-or-nothing; stale presses and presses queued before a reconnect are never replayed.
- Shell commands, HTTP requests and delays run on a bounded slow lane, so a long command no longer blocks other
  keys or the host; a button that is still running ignores a second press; commands are killed as a process
  tree on timeout or shutdown.
- Imports show every command, web request, program launch and automatic rule for approval and can be imported
  without them; variable values with shell metacharacters are refused in shell commands and percent-encoded in
  URLs; HTTP credentials can come from `$(env:NAME)` and exports replace them with such references.
- The firmware image cache counts the incoming image, evicts the least recently used images and refuses what
  cannot fit (`AD_IMG_END FULL`).
- Dependency audit in CI found eight known vulnerabilities in Pillow 12.3 (which decodes user images); Tessera now requires Pillow 13.
- Fixed: the diagnostics redaction leaked user names containing a space and `Bearer` tokens (found by its test).

### Product

- Counters and timers (saved, with labels, rings, bindings, tray notifications and end actions).
- Keys follow Windows state: microphone, speakers, media; `audio` action; `$(pc:…)` labels.
- Long-press actions; return to the previous profile after an automatic switch.
- Per-key background, label and outline colors; ambient clock screen with optional weather; the panel keeps its
  last layout without the PC.
- Editor: test (dry run), image cropper, online icon search, backups and restore, plugins, ambient settings,
  panel firmware installer with update check, diagnostics export.
- Per-app and device volume (`audio` targets `app:NAME.exe`, volume set/up/down), typing speed for `text`, a choice between matching cities, and a live *Host log* view.
- Key theme (default look for all keys, five presets), mouse actions (click, double, scroll, move).
- Plugins with scoped tokens and an event stream; AI tool adapters for Claude Code hooks and Codex notify.
- Portable defaults: programs are found when installed elsewhere, GPU sensors prefer the discrete card on any
  vendor.
- `Tessera.cmd --setup`, `--uninstall [--purge]`, `--diagnostics`; dependencies are synced only when
  `requirements.txt` changes.
- CI for the Windows host, firmware build and native LVGL tests; tag-driven release workflow.
