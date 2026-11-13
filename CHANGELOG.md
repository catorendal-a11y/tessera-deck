# Changelog

## Unreleased

- Editor: on a large screen the deck grows with the window (bounded by its height) instead of stopping at a fixed width.
- Editor: the bare ⋯ button is now four named buttons above the deck, **Profile**, **Page**, **Panel** and **More**, each with a short menu where every entry says in one line what it does; a menu opens right under its button, fits the window, and the arrow keys move through it. Clearer names: *Profile from a template*, *Page from a template*, *Clock when idle*, *Key colors*, *Save diagnostics*.
- Rail: after a shortcut, the Keys button on the panel seemed dead (the keys already showed, so nothing changed). A tap on Keys while the keys show now goes back to the page you came from, or to the profile's first page (panel firmware and host).
- Panel (new firmware): a key sinks under the finger and pulses while the PC runs its action; the second line of a wide key, the corner marks, the clock and *NO PC* are larger; the mixer has bigger mute buttons and knobs; without the PC the agents, mixer and status screens show a clear *PC not connected* card; a task that hangs the panel for 5 s restarts it.
- Editor: `/` jumps to the action search, Enter adds the first match and the arrow keys walk the list; a cleared key comes back with the Undo button in the message; the key menu shows its shortcuts, and `?` (or **More → Keyboard shortcuts**) lists them all.
- Tray: the Tessera and panel versions in the menu; **Help** opens the host log, saves diagnostics for a bug report, opens the data folder and checks for updates when you ask; a problem that lasts 30 seconds (a port held by another program, a stopped host) gets a notice; the first start asks whether Tessera should start with Windows.
- README: build it or buy one, with prices; CONTRIBUTING points to first issues. CI runs cppcheck on the firmware.
- New widget *Next meeting*: the meeting that runs now or comes next, read from the iCal address of your Google, Outlook or iCloud calendar (Program settings); repeating, cancelled and moved meetings are followed, and the address is left out of exports.
- New plugins: **Home Assistant** (show and switch lights and sensors, run scenes) and **OBS Studio** (scenes, recording, streaming, mute). Plugin settings named like a secret are left out of exports.

## 0.6.2

- Permission questions: a touch on Allow within 0.8 s of a new question no longer answers it (it was meant for what stood there before); a question too long to show in full offers Deny only (panel firmware); a lane hidden from the agents screen is not asked; a question is never shortened to fit.
- Import review and *Import without commands* also find commands inside a timer's end actions.
- Export works in the editor window (the window cancelled every download).
- Terminal editor: a backup is kept before each save (always before an import or a delete), and a step type it cannot edit no longer crashes it.
- Values of variables are no longer searched for `$(env:NAME)` in HTTP headers and bodies, so a variable cannot pull in a secret.
- A shell action that starts a program with `start` no longer waits 30 seconds and reports a failure.
- Speaker volume, mute and the mixer work on a PC without a microphone.
- Typing text with a delay no longer freezes the other keys while it types.
- Mouse *move to* lands in the right place with more than one monitor.
- A wide music key with a non-ASCII song title reacts to presses again.
- `$(profile_lock)` shows LOCKED instead of the Norwegian LÅST.
- *Test* (dry run) knows *Lock profile* and plugin actions and finds programs on PATH.
- Connect Claude Code keeps your own hook when it shares a group with Tessera's.
- Template keys no longer use arrow characters the panel font cannot draw.
- A damaged image, or a toggle state with a non-text label, gives a clear error instead of stopping the upload or the host.
- Docs: the native build's tools, which commands the panel answers, the weather city search host, flashing steps.
- Editor: Enter saves a dialog (it cancelled); keyboard focus stays where it was after a change; messages show above an open dialog; arrow keys step over a wide key; recorded hotkeys use names the host knows (punctuation, digits, media keys); Ctrl+C copies text in the host log; deck shortcuts no longer fire in other screens and dialogs; a plugin switch no longer flips back; renaming or deleting a page or profile also updates long-press and double-press steps and rail shortcuts; after a save conflict the editor says *Not saved · press Reload*; only a failed save marks the configuration *Not saved*.
- Editor: one name for one thing: a deck position is a *key* everywhere; key colors and quick icons are under *Look*; *Show on device* is gone (*Mirror on panel* does it).
- Firmware install: the dialog says the host started again only when it did, and a stalled esptool is stopped after five minutes.
- Panel (new firmware): long titles end in dots instead of running into the line below; the fader knob stays inside its track; a fader you touched follows the PC again afterwards (also after 25 days of uptime); picture keys appear once the images arrive after a panel restart; the corner marks sit in the corner of a wide key; without the PC the agents and status screens say *PC not connected* and Allow and Deny do nothing; a full settings partition is reset instead of disabling stored settings.
- Host: the reason a host could not start reaches the editor; start with Windows and the file picker work with æ, ø or å in the path; the tray shows why the panel is not connected and follows brightness and profile changes; the editor's token file is private to your account; a damaged firmware zip no longer breaks the firmware list, which is sorted by version; a timer restarted without seconds keeps its notice and actions; a key that presses a slow key runs on the slow lane; a dropped press flashes red at once; the log gets one line per page instead of one per refresh; validation errors name the page and the key; widget titles fit a two-slot key.
- Docs: actions, bind values, automatic triggers, Connect Claude Code, gauges and *NO PC* described as they are.
- Panel (new firmware): a key's text size, position (top, middle, bottom or hidden) and bold from the editor now show on the panel; with the title on top the icon moves down.
- The host sends an image again when the panel has dropped it from its 8 MiB cache, instead of leaving the key without its picture until the cable is reconnected.
- `Tessera.cmd --sensors` and `--sensors-off` also work when Tessera was unpacked from a downloaded zip (Tessera's own script runs with `-ExecutionPolicy Bypass`).
- Smaller firmware: the unused ArduinoJson library, a 14 px font, old compatibility headers and the calendar code of an earlier project are gone. `AD_TIME` answers `OK` or `INVALID`.
- Tests no longer write icons or state into `host/`, the host's dependencies have upper version bounds, the CI tools are pinned, a release runs the native UI tests first, and the README panel images show one time.

## 0.6.1

- One editor window: a double click on the tray icon, or a click while the editor was still starting, opened two or three. A second start now waits for the first and brings its window forward.
- Tray: the menu follows the status (it kept the old status line, ticks and greyed-out items), a second click on Start or Restart no longer starts a second host, and the icon shows the real state at once.
- README: a short animated tour of the panel, drawn by the firmware UI (`tools/make_demo_gif.py`); a contributing guide and issue templates.

## 0.6.0

- New panel layout (firmware protocol 4): a rail with four screens. The keys keep their six-by-three deck; the agents, mixer and status screens are new.
- Agents: one lane per AI tool with its state and last message. Allow and Deny on the panel answer Claude Code's permission questions through a hook (`deckctl hooks claude-permission`); anything unclear falls back to Claude's own dialog.
- Mixer: drag faders for the speakers, up to three programs and the microphone; mute with a tap.
- Status: eight readings with bars, and the first one over its limit is named.
- Agents screen works without any setup: working and idle, the project and the last tool come from the session files Claude Code and Codex already write. **Connect Claude Code** (⋯ menu) adds the hooks for "waiting for you" and for answering permission questions on the panel; it keeps your other hooks and makes a backup.
- A Windows notice when an agent starts waiting for you or finishes more than a minute of work; the tray says who is waiting.
- Widgets: ready-made wide keys (2 or 3 slots) for the clock, the date, the processor, the graphics card, memory, network speed, volume and the AI agents. Drag one from **Widgets** in the action list, or pick it under **Shows** on a wide key. No new firmware is needed.
- Editor tidied: the profile is the title, the page tabs sit above a larger deck, and a key's settings are three tabs (Look, Actions, Gauge) instead of a stack of folded sections.
- Editor: the action list is four tabs (Basics, Widgets, Ready-made, Apps) instead of eighteen groups in one column; a search still looks in all of them.
- A host started outside the editor (a terminal, a script) is recognised from its runtime file, so the editor no longer says "The host has stopped" while one holds the USB port.
- A key that opens a running program now brings its window to the front even when Windows refuses a background program the focus; before, the taskbar button only flashed.
- Rail dialog: the switches and the up/down buttons work (every one of them was disabled).
- New screenshots in the README and the feature list: widgets, the agents and mixer screens and the tidied editor.
- Editor: everything is drawn 15% smaller.
- Editor: the key card has room for everything (the preview beside the title and icon, every other setting full width), and the key's size is picked with three buttons: Normal, Wide, Extra wide.
- Editor: moving, pasting or duplicating a wide key checks that it fits on its row without covering another key; otherwise it is refused (move) or pasted as a normal key. Heights follow the editor's zoom, so the rail's + and the bottom of every column stay in view; on wide windows the key's settings sit in their own column.
- The editor's status line shows the panel's firmware version and says when an update is available.
- Editor: a key's steps are listed in order ("1 Open program → 2 Hotkey"), hold and double-press steps show under it, the profile rules are explained in plain words, and a meter shows how much of the panel's offline memory the page uses.
- Fixed: a changed VERSION did not reach the firmware build, so a rebuilt panel could keep reporting the old version.
- Editor: a rail on the left with the panel's four screens. Keys is the editor you know; Agents, Mixer and Status show what the panel shows right now and let you choose what goes on them, with the Claude Code connection on the Agents screen.
- Wide keys: a key can cover 2 or 3 slots (Width in the key's settings) and show the music that plays (title, artist, progress bar) or a timer (time left in a ring). Needs the new firmware.
- The editor now looks like the panel: the same dark colors, flat rounded cards, mint/cyan/purple accents and a green accent line, instead of the grey Stream Deck look.
- The panel's rail is yours to choose: **Rail …** (⋯ menu) turns Agents, Mixer and Status on or off and adds up to three shortcuts to a page of any profile. The editor's rail follows the same choice. Needs the new firmware (at most seven buttons).
- Editor layout tidied: the title, the deck, the pages, the sync bar and the key's settings share one column and scroll together; the three settings sections stack instead of floating; the action library uses one icon family and no mismatched glyphs.
- The rail dialog is rebuilt: a live preview of the rail beside the screens (switch on or off, move up or down) and the shortcuts (page from a grouped list, icon picker), with a count of the seven buttons the panel fits. The editor's rail follows the chosen order.
- Fixed: Cancel in a dialog with a required field (new page, new profile, page settings) did nothing, because the empty field blocked it.
- Fixed: the editor window could end up under the Windows taskbar; it now fills the screen minus the taskbar.
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
