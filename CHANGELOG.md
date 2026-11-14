# Changelog

## Unreleased

- Home Assistant (host side, needs panel firmware that reports `"api":1`): the **Wi-Fi and Home Assistant** dialog gets a Home Assistant section with an on switch, device name, friendly name and area (`panel.homeassistant`, sent to the panel with `AD_API_SET` when it differs), the pairing state, the panel's address and port 6053, the encryption key behind *Show key* with *Copy* and *Make new key*, and the steps to add it in Home Assistant. The key is read from the panel over USB (`AD_API_KEY`) through the owner-only control API route `POST /v1/api`, and is never stored or written to logs, the runtime file, diagnostics or exports. The host sends the profile and page names (`AD_API_OPTIONS`) and switches when Home Assistant picks one (`{"type":"ha_select"}`, unknown names are ignored). `tools/esphome_check.py` checks the API from the PC with `aioesphomeapi` in a separate venv.

- Wi-Fi (host side, needs panel firmware with protocol 5): **Panel → Wi-Fi and Home Assistant …** sends a network name and password to the panel over USB, shows the live state, address and signal, and can forget the network. The password is never stored on the PC; only `panel.wifi.ssid` is saved. The control API gets `POST /v1/wifi` for the owner token only (never for plugins), and diagnostics hide the network name, address and MAC. Older firmware is told to update and gets nothing sent. `tests/hardware_smoke.py --wifi` checks it on a real panel, asking for the password with `getpass`.
- Import: *Without commands* also removes text typed after a hotkey (Win+R, a command and Enter runs it), and the review lists such keys.
- Images: a dropped image is only read as PNG, JPEG, GIF or WebP, so Pillow's other decoders never see it.
- CI: every GitHub Action is pinned to a commit SHA, and a test keeps it that way.
- Sensors: Libre Hardware Monitor now runs with administrator rights only from a verified copy in `%ProgramFiles%\Tessera`, which other programs cannot change, and a firewall rule keeps its port 8085 off the network. Run `Tessera.cmd --sensors` again to move the sign-in task there.
- Panel: a brightness change is saved to the panel's flash at most once a minute (it still applies at once), and the panel refuses JSON nested more than 16 levels deep, so a bad message can no longer crash it or make it restart in a loop.
- Security: a key whose program is on a network share (`\\server\…`) or a web address no longer reads its *app* icon from there, which sent your Windows sign-in to that server without a key press. The key shows the default icon.
- Security: a calendar with hostile repeat rules can no longer keep the host busy for minutes; an old monthly or yearly meeting now also shows up.

- Security: the Claude Code permission hook and deckctl only talk to a running Tessera host. A program that answers on the port of a host that crashed can no longer approve a tool call or receive the token, and the editor and control API drop a connection that stalls for 10 seconds.
- Security: the editor's address holds a one-time code instead of its session key, so a copy in the browser's history no longer opens the editor, and the session key no longer travels in a cookie that other programs on 127.0.0.1 could receive. A second editor tab opened from an old address asks you to start Tessera again.
- Panel: the idle clock is bigger, in deeper colors, with a larger date and weather line, and an icon for the weather (sun, or a moon after sunset at the place, cloud, fog, drizzle, rain, snow or thunder).
- Panel: a 12-hour clock with AM/PM. *Clock format* in Panel → Display is *Same as Windows* by default, or 24-hour or 12-hour.
- Windows notifications can be switched off: *Show Windows notifications* in Program settings, or *Show notifications* in the tray menu. Answers to a tray click still show, and switching it in the tray while the editor is open no longer makes the next save conflict.
- Panel: a locked panel also ignores Allow, Deny, Stop and Open on the agents screen and the faders and mute on the mixer. A question still shows.
- Panel: Allow, Deny and Stop answer the agent the lane showed, and do nothing if that agent's state changed before the screen caught up.
- Panel: gauge keys draw a ring filled to the percentage, and the badge icon in the corner.
- Panel: a key's confirmation no longer flashes the key that took its place after a page change.
- Panel: the idle screen's line is no longer missed when it changes at the moment it is drawn.
- Panel firmware: when the display fails to start, the panel restarts instead of going silent on USB, so an unconfirmed update rolls back.
- Host: moving the panel's brightness slider (or any save that leaves the keys as they were) no longer resets toggle keys, leaves the open folder or wakes a dimmed panel.
- Host: a plugin whose log file cannot be opened is marked as failed and backs off instead of retrying every few seconds.
- Host: a weather place name can no longer break the idle clock line, and a long non-English name is cut on a whole character.
- Host: a wide pinned key that would cover a page key (or the reverse) is rejected when the configuration is checked.
- Host: a profiles.json that is briefly locked at start (antivirus, an editor saving) is no longer replaced by an older backup.
- Host: the panel's audio and media state keeps updating after an unexpected error from the audio or media library.
- Host: the control API answers 401 to a token with non-ASCII characters instead of dropping the connection.
- Firmware update: the message for a single-slot package names *Full install*, the option the editor has.
- Diagnostics: the support bundle masks key labels in the log ("Button 3: <label>"), as the editor promises. The live host log on your PC still shows them.
- Home Assistant plugin: a refused key command shows "HA error 404" (or the code it got) instead of "not reachable".
- Terminal UI: a new profile, page or template that cannot be saved shows "Not saved" and no longer closes the app.
- Editor: a step the host would refuse (key number outside 1-18, an unfinished hotkey like `ctrl+`, an address without http://, a counter, timer or variable name with spaces, Lowest above Highest, a wait over 60000 ms) stays a draft with a *Finish key* link, so the other keys still save.
- Editor: switching a toggle key back to a normal key clears *Follow PC state*; before, every later save was refused.
- Editor: renaming or deleting a page fixes triggers in every profile, and leaves triggers alone while another profile still has a page with that name.
- Editor: a pinned key can only be made wide when the slots are free on every page.
- Editor: profile and page names stop at 100 characters, the host's limit, also for copies of copies.
- Editor: a plugin asks again when its command or permissions change, even under the same version.
- Editor: a failed online icon search shows the error in the results instead of *Searching …*; Ctrl+C with text selected copies the text, not the key.
- Editor: no false "changed in another window" after restoring a backup, and no second save with an old revision while a merge retry is running.
- Host: a *Set variable* step needs a name of letters, digits, `_ . -` (the only names `$(var:…)` can read) and a value of at most 1000 characters.

## 0.8.0

- Firmware update over USB: when the panel stops acknowledging partway, the host aborts and starts the upload once more by itself. The panel keeps its running firmware either way.
- Editor: the Panel menu starts with *Display …* (brightness, dimming, quiet hours and the idle clock, which used to sit in Program settings and *Clock when idle …*) and *Panel firmware and updates …*. Program settings keeps only what the PC does: autostart, automatic profiles and the calendar.
- Editor: *Panel screens …* is gone from the Panel menu; choose what the agents, mixer and status screens show on those screens in the rail, as the Rail dialog now says.
- Editor: the Page menu has *New page*, and the Page and Profile menus each have *Delete this page* / *Delete this profile* with Undo in the toast. The settings dialogs no longer have a delete checkbox.
- Editor: the More menu starts with *Getting started* and no longer repeats *Keyboard shortcuts* (the app bar has it).
- Editor: one sentence for safe editing everywhere: "Nothing runs in the editor. Keys run only when you press them on the panel." *Run now* in Test stays the one exception.
- Editor: the action list hint and the Getting started step say what a click does (a new key on the selected empty slot or the first free one) and that a drop on a key adds a step.
- Docs: USING.md and INSTALL.md use the editor's names (Profile, Page, Panel and More menus, Look, Actions and Live tabs, the action list on the right, Program settings, Panel firmware and updates). INSTALL.md has a *First 5 minutes* section and no fixed COM port; USING.md troubleshooting starts at More → Host log.

- Editor: text is no longer scaled down in smaller windows. Body text is at least 14 px and labels at least 13 px; the app bar, rail, status bar and messages now share one scale.
- Editor: from 1280 px wide, the key's settings sit in their own column beside the deck instead of below it, and the deck preview grows with the space.
- Editor: the action list on the right folds into a narrow strip with its Actions button; the editor remembers your choice, and / opens it again.
- Editor: dim and secondary text has more contrast, and Windows' high-contrast setting raises lines and text further.
- Editor: long profile and page names and tab labels are cut with an ellipsis instead of wrapping; many pages scroll sideways.
- Editor window: the first window fits the screen, including a 1366x768 laptop, and the editor reopens at the size and place you left it.
- Getting started: on a first run the editor shows a live checklist (Host running, Panel connected, Firmware up to date, Put an action on a key, Press it on the panel) that ticks itself off from the host status. *Install firmware …* sits on the panel step, and closing the card is remembered by the host (`host/setup.local.json`).
- The first key press that reaches the PC says "It works" and lights up that key in the editor.
- New installs start with a lean home page (volume, mute, play/pause, Explorer, Terminal, screenshot, calculator, show desktop, lock) and the Status, Desktop, Audio and Tools folders, without the author's own apps.
- `Tessera.cmd` shows numbered progress lines (1/3 … 3/3) on the first start.
- The tray asks about *Start with Windows* only after the panel first connects, and that first connection says to open the editor to set up your keys.
- Editor: when no panel connects, the status bar names the cause (another program holds the USB port, firmware too old, not a Tessera panel, or no answer) and shows the host's own error on a second line.
- Editor: connection problems in the status bar have a *Show the host log* button.
- Editor: a panel with older firmware than Tessera gets a status bar notice with *Update firmware …*; *Not now* hides it until the next Tessera version.
- Editor: *Start host* in the status bar shows "Starting the host …" and keeps a failure in the bar.
- Editor: the LED and connection text open a *Panel status* window with the port, firmware, Tessera version, the next step and *Panel firmware …*.
- Panel firmware: with no panel connected the dialog chooses the full install and shows *Install anyway* at once; the choices are now *Update (keeps settings)* and *Full install (new or blank panel)*, and the protocol number shows only when it does not match.
- Panel firmware: a panel that does not answer is told to choose *Full install* and tick *Install anyway*.
- Editor: a click on an action in the list always makes a new key, on the selected slot when it is empty or else on the first free slot; drop an action on a key to add a step to it. A toast says which key got it.
- Editor: a new key opens on the Look tab with the cursor in Title, so you name it first.
- Editor: pasting a key or placing a program on a key that is in use says "Replaced key N" with an Undo button.
- Editor: an unfinished key gets a yellow dot and a tooltip, and the sync line links to it. The other keys keep saving; the panel gets the unfinished key without its unfinished part.
- Editor: adding Open folder opens Create a subpage with the key name filled in. The key gets the page as its name and target, the editor opens the new page, and a toast says Back is on slot 17. The list names are now "Open folder (with Back key)" and "Go to page (no Back key)".
- Editor: a step's action type is a menu in the step title, so a wrong pick changes in place.
- Editor and host: a key with Position set to Hide text may have an empty name (icon only).
- Editor: drag a key onto a page tab to move it to that page. Each page remembers its selected key.
- Editor: the sync line has a "Show this page on the panel" button when the panel shows another page, and says "✓ On the panel" after a save. The checkbox is now "Panel follows the page I edit".
- Editor: the Look tab has an **Action** row with the field a key needs most: **Record** for a hotkey, **Choose program …** for an open action, or a summary that opens the steps.
- Editor: **Test**, **Copy**, **Paste**, **Clear** and **Move to slot** sit in a footer under the inspector tabs, so they show on every tab. *Hold to confirm* moved to the Actions tab, and *Add action …* is now **＋ Step …**.
- Editor: the inspector tab *Gauge* is now **Live**.
- Editor: the icon library stays open after you pick an icon, so you can try a few. Icon color has 8 swatches, *Key colors* is a row in the Look tab, and *Quick icons* are gone.
- Editor: **Test** is also in the Look header, and the test dialog has **Run now on this PC**. It shows the page on the panel and presses the key there, and asks first when the key runs a command, sends a web request or types text.
- Editor: a widget key shows *Widget: Clock · Change …* instead of title, icon and text rows that did nothing, and its tile shows the same text as the panel.

## 0.7.0

- Install: `Tessera.cmd` installs the host packages from `host/requirements.lock`, where every package is pinned with its SHA-256 hash (`--require-hashes`), and says clearly when Python is missing or older than 3.11.
- Releases: the notes are the matching `CHANGELOG.md` section, the host tests run before publishing, and the zips carry a build attestation (`gh attestation verify`). [Install](docs/INSTALL.md) explains the SmartScreen warning and how to check a download against `SHA256SUMS`.
- Desk console and dock: a print table (orientation, layer height, supports, infill, walls, screws) in `hardware/README.md`, and the console in the README.
- Bug reports ask for the Windows version and the *Save diagnostics* file; blank issues are off. Dependabot proposes weekly grouped updates for GitHub Actions and the host packages.
- Tray: a host that dies without you pressing Stop starts again by itself (after 5 s, 15 s, 60 s, then every 5 minutes), with one notice per burst instead of one per attempt.
- Host log: three older logs are kept (deck.local.log.1 to .3), both at start and while the host runs. **Help → Recent problems** in the tray lists the last 20 failures from the log, and diagnostics include them.
- HTTP actions: an answer with an error status (4xx or 5xx) now fails the action with its code. The import review names the host each web request goes to.
- Backups: a profiles file the host cannot use is never backed up, so it cannot push good copies out. If profiles.json is broken at start, the newest good backup is restored, the broken file is kept as profiles-unreadable.local.json, and the tray says so.
- Updates: the tray's check says *Update available: <version>* with the first lines of the release notes; the editor's check gets the same excerpt.
- Plugins: the editor asks before a plugin first runs (and again for a new version), listing what it may do and the program it runs; secret settings (tokens, passwords, API keys) are stored encrypted for your Windows account, so profiles.json and backups no longer hold them in plain text (existing ones are encrypted on the next save).
- Control API: each token is limited to 20 calls a second (bursts of 40, then `429`), and every change is logged with the caller's name.
- New actions: *Copy to clipboard* puts a text (with $(...) variables) on the clipboard and can paste it; *Window* minimizes, maximizes, restores or closes the window in front or a named program's, toggles always on top, moves it to the next monitor or brings a program to the front; *Toggle variable* switches a variable between two values on each press. The library has Always on top, Close window and Paste date keys.
- Firmware updates over USB with rollback: the flash now has two 6 MB app slots, *Application only* goes over the panel's own USB connection and the bootloader goes back to the previous firmware if a new one never reaches the host. The first install of this firmware must use *Everything* (the installer says so).
- A hung screen or USB loop now restarts the panel by itself (task watchdog on both).
- The host logs when the panel restarted and why, and shows a notice after a crash, hang or power dip.
- The panel keeps every layout up to 8 KB for use without the PC (was 3,800 bytes), with the previous one as a backup; a layout over 8 KB gets a clear "too big" answer.
- Panel contrast: secondary text is brighter (#8FA0A8) and larger (20 px) for headings' summaries, agent states and projects, fader and reading names; a native test keeps every text colour at WCAG 4.5:1 or better.
- Hold to confirm: a key marked *Hold to confirm* in the editor runs only after a 0.6 s hold while a ring fills on it; lifting the finger or sliding off earlier does nothing (panel firmware and host).
- Panel lock: a new *Lock panel* step (lock, unlock or toggle) makes the panel ignore taps on keys and the rail; the logo becomes a lock badge, and holding it for 2 s unlocks the panel and tells the PC.
- Swipe right on the keys goes back, like Keys on the rail after a shortcut (there are no next or previous pages, so a swipe left does nothing); a swipe never presses the key it starts on.
- About sheet: a long press on the panel's logo shows the firmware version, whether the PC is connected and a brightness slider; the level is saved on the panel and in the settings, so the PC keeps it. Tap outside to close.
- Editor: questions and name prompts open in the editor's own dialog instead of the browser's; deleting a profile or a page no longer asks first and offers Undo instead.
- Editor: a bar at the bottom stays while something blocks you (host stopped, no panel, a save conflict, an unreadable configuration file) and has the button that fixes it (Start host, Reload, Restore a backup).
- Editor: a Getting started card (choose a template, drag an action onto a key, test it) shows while no key is set up, and More → Getting started opens it again.
- Editor: importing a file first shows its profiles, pages and keys and the risky actions it holds, then adds them as new profiles or replaces the configuration; an export says what it left out (calendar address, plugin passwords, web request credentials).
- Editor keyboard: the action tabs, the key-settings tabs and the page chips are one Tab stop each (the arrow keys, Home and End move along them); every dialog gives the focus back to what opened it; every control shows where the focus is; the panel screens are no longer read out on each update.
- Editor: **Alt+arrow** moves the selected key to the next slot (a key there changes places with it), and the key menu has **Move to slot …**; while dragging, the label says what the drop does (move, swap, add as the next step, replace).
- Editor wording: *Test (nothing runs)* everywhere, *Show on panel* instead of *Mirror on panel*, **Program settings** in the app bar, a visible **Keyboard shortcuts** button, and the Redo tooltip names Ctrl+Y and Ctrl+Shift+Z.
- CI: a smoke test opens the editor in a real browser and checks the deck, two dialogs, the focus and axe accessibility rules. `--no-browser` prints the editor's address.
- Docs: new panel and editor images, and a longer demo animation (17 scenes: folders, window and meeting keys, pages that follow the app, the idle clock and the editor). In the editor a long widget description no longer runs past the settings panel.
- Long runs: the panel tells the host which screen shows, so the sound mixer is read every second only on its screen (otherwise every 5 s). Plugin folders are read again only when they change, the AI session history is walked every 10 s instead of 2 s, an unchanged status file is not rewritten, and the host log is kept under 5 MB while the host runs.
- Performance: images reach the panel about 4 times faster, and the panel reads USB in 2 KB blocks instead of locking per byte. Hidden screens, a dark screen and the clock no longer redraw or animate keys. The host stops refreshing keys under a dark screen, skips nvidia-smi when a sensor tool has the GPU, and caches the program list. The editor stops polling in a hidden tab and redraws the rail only when it changes.
- Screen switching: a waiting permission question is never covered by the clock or a dark screen, after a reconnect it pulls the panel to Agents again, and once answered the panel goes back to the screen you had; waking and leaving the clock always show the keys; switching screens on the rail counts as use; a shortcut to the page you are in leaves a folder. Allow and Deny show only for a real question. The editor merges a save made elsewhere (tray brightness) instead of refusing; the panel asks the PC again for icons it lost; *Import without commands* drops step shortcuts left empty.
- A full logic review fixed 51 problems, among them: a slow key could run whatever key was at its place after a page change; slow typing froze every other key; a PowerShell variable could inject code; firmware install could flash the wrong board; the host could be started during a flash; daily triggers ran again after every restart; agent states stuck after a tool was killed; Outlook calendars with quoted time zones were unreadable; dropped actions could land in a Held list; an online icon picked for a rail shortcut went onto a key; a Claude notice showed Allow and Deny that answered nothing; a broken profiles file now says so in the editor.
- Rail fixes: Keys goes back only after a shortcut and keeps your page otherwise; a shortcut is forgotten once you move on your own; a tap on a dimmed panel only wakes it; without the PC a shortcut does nothing instead of flashing; the steps of rail shortcuts are reviewed on import, stripped by *Import without commands* and follow renamed or deleted pages and profiles; long page names no longer push the rail past the panel's line limit.
- Rail shortcuts can run steps like a key (copy them from one of your keys, give the shortcut a name) without leaving the screen, and any icon from the library can be used (panel firmware 0.6.3; an older panel simply leaves such shortcuts out).
- Rail dialog: the preview names every place and shows the free ones, a shortcut shows its profile and page, shortcuts are numbered and can be moved, the icon row is labelled, and a line says what a shortcut does and how Keys brings you back.
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
