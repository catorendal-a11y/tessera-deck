# Changelog

## Unreleased

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

## 0.5.0

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
