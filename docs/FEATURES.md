# Features

[Back to the README](../README.md)

Tessera turns the 1024 × 600 touchscreen of the **GUITION 7-inch ESP32-P4 display board** into a Stream Deck-style panel with 18 keys and four screens. A small Windows host owns the USB connection and runs the actions. It also serves the editor, which shows the same keys as the panel.

This page lists what Tessera does, including the changes under *Unreleased* in the [changelog](../CHANGELOG.md). For how to use each part, see [Using Tessera](USING.md).

| Editor: a page of widgets | Editor: status page with live gauges |
|---|---|
| <img src="images/editor-widgets.png" alt="A page of widgets in the editor, with the key settings in tabs"> | <img src="images/editor-status.png" alt="Status page with live gauges in the editor"> |

| Panel: main page | Panel: widgets on wide keys |
|---|---|
| <img src="images/panel-main.png" alt="Main page drawn by the panel firmware UI"> | <img src="images/panel-widgets.png" alt="Clock, date, volume, processor, graphics card, memory, network and AI agents widgets"> |

| Panel: agents screen | Panel: mixer screen |
|---|---|
| <img src="images/panel-agents.png" alt="Claude Code asks for permission; Deny and Allow answer it"> | <img src="images/panel-mixer.png" alt="Faders for the speakers, three programs and the microphone"> |

| Panel: status page |  |
|---|---|
| <img src="images/panel-status.png" alt="Status page drawn by the panel firmware UI"> |  |

<sub>The editor images show the real editor with this PC's sensor values. The panel images are drawn by the real firmware UI (LVGL) in a native build, not photographed: the key pages with `tools/render_screens.py`, the agents and mixer screens by the native UI test with sample data.</sub>

## On the panel

| Part | What it does |
|---|---|
| Keys | A fixed 6 × 3 grid drawn by LVGL. Values and labels update in place, so a key is not rebuilt under your finger. The grid is rebuilt only when the page changes. |
| Rail | The buttons down the left edge: the Keys, Agents, Mixer and Status screens, then up to three shortcuts to your own pages. You choose the screens, their order and the shortcuts under **Panel → Rail …**. |
| Agents screen | Shows what Claude Code, Codex and ZCode are doing: each tool's icon, since when it has worked or waited, what it does and its project folder. A permission question from Claude Code shows here and is never covered by the clock or a dark screen. Touch *Allow* or *Deny* to answer, *Open* to bring the tool's window forward, or *Stop* while it works. |
| Mixer screen | Faders for the speakers, up to three programs and the microphone. |
| Status screen | Live gauges for the PC. |
| Clock screen | An idle clock made of brand-colored tiles, with optional weather from Open-Meteo for a city you choose and an icon for sun, cloud, fog, drizzle, rain, snow or thunder. The clock is 24-hour or 12-hour with AM/PM; *Clock format* in Panel → Display follows Windows by default. |
| Offline layout | The panel keeps the last layout (up to 8 KB, with the previous one as a backup) and shows it when the PC is off. |
| About sheet | A long press on the logo shows the firmware version, whether the PC is connected and a brightness slider. Tap outside to close. |

### Touch

| Gesture | Result |
|---|---|
| Tap a key | Runs its actions. |
| Hold a key for about half a second | Runs the key's *Held* actions, if it has any. |
| Two quick taps | Run the *Double-press* actions. A key with a double press waits about a third of a second before its normal action runs. |
| Hold a key marked *Hold to confirm* | Runs only after a 0.6 s hold while a ring fills. Lifting or sliding off earlier does nothing. |
| Swipe right on the keys | Goes back, like Keys on the rail after a shortcut. A swipe never presses the key it starts on. |
| Touch a dark screen | Wakes the panel without pressing a key. |
| *Lock panel* step | The panel ignores taps on keys and the rail. The logo becomes a lock badge. Hold it for 2 s to unlock. |

### Keys and widgets

- A key can cover two or three slots (wide keys).
- Widgets on wide keys: clock, date, processor, graphics card, memory, network speed, volume, AI agents and next meeting. A wide key can also show the music that plays or a timer's countdown.
- Real app icons come from the Windows shell at 256 px (Store apps, shortcuts and aliases included). You can also use 1,895 bundled [Lucide](https://lucide.dev) icons and your own PNG, JPEG, GIF and WebP images.
- Live gauges cover CPU, GPU, VRAM, RAM, disk, network, uptime, temperatures, power, fan speed and FPS. The panel shows the value in the gauge's color, amber and red at the thresholds.
- Microphone, speaker and media keys show the real Windows state (muted, live, playing) and flip on their own. Labels can show the current track and volume.
- Secondary text meets WCAG 4.5:1 contrast, checked by a native test.

### Brightness and reliability

- The panel dims after inactivity or when the PC locks. Quiet hours lower the brightness at night.
- A hung screen or USB loop restarts the panel by itself. The host logs the restart and why, and shows a notice after a crash, hang or power dip.
- Firmware updates go over USB. The flash has two 6 MB app slots, and the bootloader returns to the previous firmware if a new one never reaches the host.

## In the editor

<p align="center">
  <img src="images/editor-main.png" alt="The Tessera editor: the keys of the panel, the settings of the selected key and the action list" width="900">
</p>

### Layout

| Area | What it holds |
|---|---|
| App bar | The **Profile**, **Page**, **Panel** and **More** menus, *Program settings* and *Keyboard shortcuts*. |
| Rail and deck | The panel's rail on the left and the keys in the middle, with a tab for each page. |
| Key settings | The selected key's settings. From 1280 px wide they sit in their own column beside the deck. |
| Action list | On the right, with the tabs Basics, Widgets, Ready-made and Apps. It folds into a narrow strip, and `/` opens it and searches. |
| Status bar | Stays while something blocks you and has the button that fixes it. |

Text is at least 14 px, dim text has more contrast, and Windows' high-contrast setting raises lines and text further. The editor opens at the size and place you left it.

### Menus

| Menu | Contents |
|---|---|
| Profile | New profile, a profile from a template, duplicate, *Profile settings …*, *Delete this profile*. |
| Page | New page, a page from a template (Meetings, Coding, Media, Browser), duplicate, *Page settings …*, *Delete this page*. |
| Panel | *Display …* (brightness, dimming, quiet hours, idle clock, clock format), *Panel firmware and updates …*, *Rail …*, *Key colors …*. |
| More | *Getting started*, *Connect Claude Code …*, *Plugins …*, export, import, *Restore a backup …*, *Host log …*, *Save diagnostics*. |

Deleting a page or a profile asks no question. A toast offers Undo.

### Setting up keys

- A click on an action in the list makes a new key on the selected slot if it is empty, otherwise on the first free slot. Drop an action on a key to add a step to it. A toast says which key got it.
- A new key opens on the **Look** tab with the cursor in Title.
- The key settings have three tabs. **Look** holds the title, icon, colors, text position and an **Action** row with the field the key needs most. **Actions** holds the steps, the Pressed, Held and Double-press triggers and *Hold to confirm*. **Live** holds gauges and widgets. **Test**, **Copy**, **Paste**, **Clear** and **Move to slot** sit under the tabs.
- Drag a key to move or swap it, or onto a page tab to move it to that page. **Alt+arrow** moves the selected key to the next slot. Copy, paste, duplicate, undo and redo work, and a key can be pinned to all pages. Pasting over a key in use says "Replaced key N" with Undo.
- *Open folder (with Back key)* creates a subpage and its Back key. *Go to page (no Back key)* only jumps. Keys can also toggle between 2 and 8 states and run multi-step actions. A step's action type is a menu in the step title.
- A key set to *Hide text* may have an empty name.
- An unfinished key gets a yellow dot. The other keys keep saving, and the panel gets the unfinished key without the unfinished part.
- The sync line says whether the page is on the panel, offers *Show this page on the panel* and says "✓ On the panel" after a save. *Panel follows the page I edit* keeps the panel on the page you edit.

### Looks

- Background, label and outline colors per key, and default colors under **Panel → Key colors …**.
- An icon library that stays open while you try icons, an image cropper and optional online icon search (Iconify) next to the 1,895 offline icons.
- A widget key shows *Widget: Clock · Change …* and the same text as the panel.

### Actions

- Over 120 ready-made actions and 10 profile templates for Windows, windows and desktops, PowerToys, GitHub Desktop, VS Code, browsers, meetings (Teams, Zoom, Discord), media, Codex, Claude Code and ZCode.
- Actions added in 0.7.0: *Copy to clipboard*, *Window* (minimize, maximize, restore, close, always on top, next monitor, bring a program to the front), *Toggle variable* and *Lock panel*.
- Counters and timers with labels (`$(counter:laps)`, `$(timer:tea)`), a countdown on the key, notifications and end actions. They are saved, and a running timer keeps counting while Tessera is closed.
- An HTTP action fails with the status code when the answer is 4xx or 5xx.

### Testing

- **Test** explains what a key would do and checks paths, hotkeys and web addresses. It runs nothing.
- *Run now on this PC* shows the page on the panel and presses the key there. It asks first when the key runs a command, sends a web request or types text.
- Nothing else runs in the editor. Keys run only when you press them on the panel.

### First run and problems

- *Getting started* is a live checklist: Host running, Panel connected, Firmware up to date, Put an action on a key, Press it on the panel. It ticks itself off, and closing it is remembered. **More → Getting started** opens it again.
- The first key press that reaches the PC says "It works" and lights up that key.
- New installs start with a small home page and the Status, Desktop, Audio and Tools folders.
- When no panel connects, the status bar names the cause (another program holds the USB port, firmware too old, not a Tessera panel, or no answer), shows the host's error and has a *Show the host log* button.
- A panel with older firmware gets a notice with *Update firmware …*. The LED and connection text open a *Panel status* window.
- *Panel firmware and updates …* offers *Update (keeps settings)* and *Full install (new or blank panel)*, with verified packages and an update check.

### Keyboard and accessibility

- The action tabs, key-settings tabs and page chips are one Tab stop each. Arrow keys, Home and End move along them.
- Dialogs return the focus to what opened them, and every control shows its focus.
- CI opens the editor in a real browser and checks the deck, two dialogs, the focus and axe accessibility rules.

## Actions and automation

- **Smart profiles** switch by the foreground program, process or window title and return to the earlier profile when the program loses focus. A *Lock profile* key keeps the current profile.
- **Scriptable:** a local control API and the `deckctl` command line let hooks and scripts set variables, colors, button states and pages, for example a Claude Code status light. Each token is limited to 20 calls a second.
- **Integrations:** plugins with their own limited API tokens ([PLUGINS.md](PLUGINS.md)), with Home Assistant and OBS Studio included, and adapters that turn Claude Code hooks and Codex notifications into key states. The editor asks before a plugin first runs and lists what it may do.

## Sensors, safety and upkeep

- **Free sensors:** Windows performance counters out of the box. The graphics driver adds GPU temperature, power, fan speed and clock without administrator rights (AMD through ADL, NVIDIA through `nvidia-smi`). [Libre Hardware Monitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) adds CPU temperature and power. `Tessera.cmd --sensors` starts it at every sign-in (one Windows prompt) and `--sensors-off` undoes it.
- **Quiet when you want:** Windows notifications (panel connected or gone, an agent waiting, a timer that ends) can be switched off in Program settings or the tray menu.
- **Safe by default:** verified device identity, a bounded action queue, long commands that never block other keys, and a review before an import. An export leaves out the calendar address, plugin passwords and web request credentials. Plugin secrets are stored encrypted for your Windows account.
- **Backups:** rotating backups with restore. A broken `profiles.json` is never backed up, and the newest good backup is restored at start.
- **Tray app and autostart:** start with Windows and control the host from the tray. A host that dies starts again by itself.
- **Upkeep:** `Tessera.cmd --setup`, `--uninstall` and `--diagnostics`, and a host log kept under 5 MB with three older logs.

Missing features are listed in the [roadmap](ROADMAP.md).
