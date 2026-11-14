# Using Tessera

[Back to the README](../README.md)

This guide covers daily use of the editor and the panel. [Install](INSTALL.md) covers setup and flashing.

## The editor at a glance

The editor is laid out like the panel.

| Area | What it does |
|---|---|
| Rail (left) | Switches between **Keys** and the agents, mixer and status screens. The **+** at its foot opens *Rail …*. |
| Action list (right) | Four tabs: **Basics**, **Widgets**, **Ready-made** (Windows, browser, meetings, media) and **Apps** (your installed programs and app packs). The search looks in all of them. A button folds the list into a narrow strip; `/` opens it again. |
| Deck (middle) | The **Profile** selector, the **Profile**, **Page**, **Panel** and **More** menus, the keys, and the page tabs with **＋** for a new page. |
| Key settings | A click on a key opens its settings: beside the deck from 1280 px wide, below it on a narrower window. |
| Status bar (bottom) | Appears only when something blocks you, names the cause and has the fix button. |

Key settings have three tabs, with **Test**, **Copy**, **Paste**, **Clear** and **Move to slot** underneath:

| Tab | What it holds |
|---|---|
| **Look** | Title, icon, icon color, text size and position, the key's size (Normal, Wide, Extra wide) and the **Action** row with the field a key needs most |
| **Actions** | *Key type* (Normal key or Toggle key), the steps for **Pressed**, **Held** and **Double-press**, **＋ Step …** and *Hold to confirm* |
| **Live** | *Live gauge* and *Follow PC state* |

Nothing runs in the editor. Keys run only when you press them on the panel. The one exception is **Test** on a key and then *Run now on this PC*.

| Menu | What it holds |
|---|---|
| **Profile** | New profile, *Profile from a template …*, Duplicate, *Profile settings …*, *Delete this profile* |
| **Page** | New page, *Page from a template …*, Duplicate, *Page settings …*, *Delete this page* |
| **Panel** | *Display …*, *Panel firmware and updates …*, *Rail …*, *Key colors …* |
| **More** | *Getting started*, *Connect Claude Code …*, *Plugins …*, *Export to a file*, *Import from a file …*, *Restore a backup …*, *Host log …*, *Save diagnostics* |

**Program settings** in the top bar holds only what the PC does: starting the host at sign-in, Windows notifications, switching profiles by program, and the calendar for the Next meeting widget.

A profile holds pages. A page holds up to 18 keys, and slot 18 is the pinned **Home** key. Changes save by themselves; the line under the deck says when the panel has them. The editor keeps your edits as you make them, and Undo (Ctrl+Z) takes back the last one, including a deleted page or profile.

## Tasks

### Add an app

1. Open the **Apps** tab in the action list, then *Installed programs …*.
2. Drag a program onto a key. A click puts it on the selected key.
3. Or choose *Choose program file …* to pick an `.exe` by hand.

Tessera fetches the program's icon. The key gets an *Open program / file* step. To bring a running program to the front instead of starting another copy, tick *Focus open window* in that step.

### Add a hotkey

1. Click **Hotkey** in the action list. A new key appears on the selected empty slot or the first free one, and the toast says which.
2. On the **Look** tab, type the name in *Title*.
3. In the **Action** row, press **⌨ Record**, then press the combination. **Esc** cancels.

A media key works the same way.

### Add a folder

1. Click **Open folder (with Back key)** in the action list.
2. *Create a subpage* opens with the key's name filled in. Press *Save*.
3. The editor opens the new page. Back is on slot 17.

**Go to page (no Back key)** switches to a page without adding Back.

### Add a widget

A widget is a wide key that shows something live. Open the **Widgets** tab and drag one onto a key with free slots to its right (two or three, depending on the widget).

| Widget | Shows |
|---|---|
| Clock | The time, the weekday and date, and how far the day is |
| Date | The date, the week number and the day of the year |
| Processor, Graphics card | Load with a bar, temperature, clock speed or frames per second |
| Memory | How much memory is in use |
| Network | Download and upload speed |
| Volume | Speaker level, muted or not, and the microphone |
| AI agents | Which AI tools are working and which wait for you |
| Next meeting | Its name, and when it starts or *Now · until 10:30* |
| Music (under *Shows*) | The track, the artist and how far it is |
| Timer (under *Shows*) | The time left of a named timer, as a ring |

To change a widget, open the key's **Look** tab and press *Widget: … · Change …*. To make an ordinary key wide, choose **Wide** or **Extra wide** under *Size* and pick a widget under *Shows*. The slots to its right must be free, and a wide key cannot run past the end of the row.

A widget does nothing when pressed until you give it steps on the **Actions** tab.

**Next meeting** needs your calendar's secret iCal address in **Program settings** (*Calendar for the Next meeting widget*). Google Calendar: the calendar's settings, *Secret address in iCal format*. Outlook: *Settings → Calendar → Shared calendars → Publish a calendar*, the ICS link. iCloud: share the calendar publicly. Tessera reads it every five minutes, follows repeating, cancelled and moved meetings, and leaves the address out of exports. Times in UTC are converted to the PC's time; times with a time zone name are read as the PC's local time.

### Make a macro with several steps

A key runs its steps in order.

1. Select the key and open the **Actions** tab.
2. Pick **Pressed**, **Held** or **Double-press** for when the steps run. A held key runs after about half a second.
3. Add steps with **＋ Step …**, or drop an action from the list on the key.
4. Drag a step to reorder it, or use its ↑ and ↓ buttons. A step's type is a menu in its title.
5. Put **Wait** steps between steps that need time.

*Hold to confirm* on the same tab makes the panel run the key only after a 0.6 s hold, with a ring that fills. It cannot be combined with Held or Double-press steps.

For a toggle, set *Key type* to **Toggle key**. Each press runs the current state's steps and shows the next state. *Edit state* picks the state to edit. On the **Live** tab, *Follow PC state* makes the key follow the microphone, the speakers, media playback or a timer instead of the presses.

### Move, copy and replace keys

| Do this | Result |
|---|---|
| Drag a key to a slot | Moves it; a key there changes places with it |
| Drag a key onto a page tab | Moves it to that page |
| Alt+arrow, or *Move to slot* | Moves it to the next slot |
| Ctrl+C, Ctrl+V | Copies and pastes; pasting onto a used slot says "Replaced key N" with Undo |
| Ctrl+D | Duplicates the key to a free slot |
| Pin (Look tab) | Shows the key on every page |

A key with a yellow dot is unfinished. The other keys keep saving, and the panel gets the unfinished key without its unfinished part.

### Profiles that follow the app

A profile can switch in by itself when a program is in front.

1. Open **Profile → Profile settings …**.
2. Under *Add a running program*, choose the program. Or type rules in *Automatic profile switching rules*, separated by commas.
3. Tick *Use as default profile* for the profile to show when no rule matches.

Rules look like `chrome.exe`, `process:claude.exe` or `title:codex`. Turn the whole feature off with *Switch profile automatically by active program* in **Program settings**. The *Lock profile* action locks or unlocks automatic switching from a key. **Profile → Profile from a template …** gives you ready-made profiles for browsers, Windows and AI tools.

### The rail and the panel's screens

The rail on the left of the panel switches between your keys, the AI **agents**, a sound **mixer** and the PC's **status**.

- **Which screens and shortcuts:** open **Panel → Rail …** (or **+** in the editor's rail). Turn the agents, mixer and status screens on or off, put them in order and add up to three shortcuts. The panel has room for seven places; the preview shows which are free. Press *Apply*.
- **A shortcut** opens a page of any profile, or runs steps like a key without leaving the screen you are on (copy the steps from one of your keys and give it a name). It can use any icon from the library. After a page shortcut, a tap on Keys takes you back. Step shortcuts need panel firmware 0.6.3 or later.
- **What a screen shows:** click that screen in the editor's rail.

### The mixer

Click **Mixer** in the editor's rail. *Programs* takes up to three names that end in `.exe`, for example `spotify.exe, chrome.exe`. Leave it empty to use the programs that play sound. *Microphone* adds a microphone fader. The faders show the PC's levels right now.

The **Status** screen has a *Show* box for each reading: CPU load, CPU temperature, RAM, disk, GPU load, GPU temperature, video memory and download speed.

### The agents screen and Claude Code

**Agents** shows which AI tools work and which wait for you, and ticks *Show on panel* per tool. Working and idle come from the tools' own session files.

On the panel, each tool gets a lane with its icon, its state and the time it started (*working since 14:12*, *waiting for you since 14:31*), what it does now and its project folder. The buttons on the right depend on the state:

| State | Buttons |
|---|---|
| Asks a permission question | *Deny* and *Allow* |
| Waits in its own window | *Open* |
| Working | *Open* and *Stop* |
| Idle | *Open* |

*Open* brings the tool's window to the front. When no tool runs, the screen says so.

To see what Claude Code is doing, and to answer its permission questions on the panel:

1. Open **More → Connect Claude Code …** (or *Connect …* on the Agents screen).
2. Tick *Show what Claude Code is doing (working, waiting for you, idle)* and *Answer Claude's permission questions on the panel*. Press *Apply*.
3. Restart Claude Code.

This adds hooks to `~/.claude/settings.json`, keeps your other hooks and makes a backup first. The question appears on the agents screen, and **Allow** or **Deny** is the answer. If the panel is not connected, nobody answers within 25 seconds, or the request is too long to show in full, Claude Code shows its normal dialog. Tessera never allows anything on its own. To do it by hand, merge the output of `python host\deckctl.py hooks claude` and `python host\deckctl.py hooks claude-permission`.

### Display settings

Open **Panel → Display …** (or the tray's *Brightness* menu).

| Setting | What it does |
|---|---|
| *Panel brightness* | The normal level |
| *Dim the panel after* | How long without a press before it dims, or *Never*. It also dims when Windows locks. |
| *Brightness when dimmed* | The level while dimmed, or *Off* |
| *Quiet hours* and *Brightness during quiet hours* | A lower level between two times, for example at night |
| *Clock format* | *Same as Windows* (the default), *24-hour* or *12-hour* with AM/PM, for the idle clock and the rail |
| *Show a big clock when the panel has been idle* and *Show it after* | The idle clock. Touch the panel to get the keys back. |
| *Weather for (city, optional)* and *Temperature unit* | Weather on the idle clock from open-meteo.com every 15 minutes, with an icon for sun, moon (after sunset there), cloud, fog, drizzle, rain, snow or thunder. Leave the city empty for no weather and no internet use. |

The first touch on a dimmed panel only wakes it; it does not press a key. A long press on the panel's logo opens an About sheet with a brightness slider. The panel keeps its brightness across restarts.

Windows notifications (panel connected or disconnected, a host that stopped, an agent waiting or done, a timer that ends) can be switched off with *Show Windows notifications* in **Program settings** or *Show notifications* in the tray menu. Answers to what you click in the tray still show.

**Panel → Key colors …** sets the default background, text and outline for every key without colors of its own.

### Back up, export and import

- **Automatic backups:** Tessera keeps the latest 30 while you edit. **More → Restore a backup …** goes back to an earlier save and keeps the current one as a backup too.
- **Export:** **More → Export to a file** writes your profiles and keys. It leaves out secrets: the calendar address, plugin passwords and web request credentials.
- **Import:** **More → Import from a file …** first shows the file's profiles, pages and keys and the risky actions in it, including the host each web request goes to and every automatic rule. Then choose *Add as new profiles* (your profiles stay; rules, rail and settings in the file are not used) or *Replace the configuration*. You can undo an import.

If `host/profiles.json` is broken at start, Tessera restores the newest good backup and the tray says so.

### Keyboard shortcuts

**⌨ Keyboard shortcuts** in the top bar, or `?`, shows the list.

| Keys | Does |
|---|---|
| `/` | Search the actions. Enter adds the first match; ↓ walks the list. |
| Arrow keys | Move between keys on the deck |
| Alt + arrow keys | Move the selected key to the next slot |
| F2 | Rename the selected key |
| Del | Clear the selected key |
| Ctrl+C, Ctrl+V | Copy and paste a key |
| Ctrl+D | Duplicate the key to a free slot |
| Ctrl+Z | Undo |
| Ctrl+Y, Ctrl+Shift+Z | Redo |
| Ctrl+S | Save now |
| Shift+F10 | Open the key menu |

## Reference

### Actions

| Editor name | Type in `profiles.json` | What it does |
|---|---|---|
| Hotkey | `hotkey` | Press a key combination or media key |
| Type text | `text` | Type text |
| Open program / file | `open` | Open a program, file, folder or URL, optionally focusing a running program |
| Run command, HTTP request | `shell`, `http` | Run a command or call an address; an error status (4xx, 5xx) fails the action |
| Wait | `delay` | Wait between steps |
| Open folder (with Back key), Back, Go home, Go to page (no Back key), Switch profile | `folder`, `back`, `home`, `page`, `profile` | Navigate |
| Trigger another key | `press` | Run another key |
| Set variable, Toggle variable | `set`, `toggle` | Set a variable, or switch it between two values |
| Set key state | `state` | Set a toggle key's state (`next` or a state number) |
| Mute / unmute audio | `audio` | Mute, unmute or set the volume of the speaker, the microphone or one program (`app:NAME.exe`) |
| Counter, Timer | `counter`, `timer` | Change a counter; start, pause, resume, stop or toggle a timer |
| Mouse | `mouse` | Click (left, right, middle or double), scroll, or move the pointer |
| Switch screen | `screen` | Show the clock, the keys, or switch between them |
| Lock profile, Lock panel | `profile_lock`, `panel_lock` | Lock or unlock automatic profile switching; make the panel ignore taps (hold the logo for 2 s to unlock) |
| Copy to clipboard | `clipboard` | Put text on the clipboard and optionally paste it |
| Window | `window` | Minimize, maximize, restore or close a window, toggle always on top, move it to the next monitor or bring a program to the front |
| Plugin (no editor name; added by plugins) | `plugin` | Send a command to a [plugin](PLUGINS.md) |

### Labels and variables

A key's title and text steps can use `$(time)`, `$(date)`, `$(profile)`, `$(page)`, `$(profile_lock)`, `$(agent:claude)`, `$(var:name)`, `$(stat:cpu_temp)`, `$(counter:name)`, `$(timer:name)` and the live PC values `$(pc:mic)`, `$(pc:speaker)`, `$(pc:volume)`, `$(pc:track)`, `$(pc:artist)`, `$(pc:media)` and `$(pc:playing)`. `$(pc:track)` shows *No music* when nothing plays.

In a `shell` command, put a value in double quotes (`notify.exe "$(pc:track)"`). Tessera refuses values with shell metacharacters; spaces are allowed.

A toggle key can follow the PC with `"bind": "mic_muted" | "speaker_muted" | "media_playing" | "timer-running:NAME"` (state 1 is off, state 2 is on). A key can change color with a variable: `"status": { "var": "claude", "colors": { "working": "#FFB74D" } }`. The Claude Code profile does this on its first key.

### Automatic actions

`triggers` at the top of `profiles.json` is a list of `{"when": {...}, "actions": [...]}`. `when` is one of:

| `when` | Runs |
|---|---|
| `{"type": "startup"}` | When the host starts |
| `{"type": "interval", "seconds": 60}` | Every 60 seconds |
| `{"type": "daily", "at": "08:30"}` | Every day at that time |
| `{"type": "file", "path": "..."}` | When the file changes |
| `{"type": "variable", "name": "claude"}` | When the variable changes |

Import shows every automatic rule before it can run.

### Live gauges and sensors

A key becomes a gauge with the **Live** tab's *Live gauge* field. In `profiles.json` it is a `gauge` block:

```json
{
  "label": "CPU TEMP",
  "icon": "lc:e0a9",
  "gauge": { "key": "cpu_temp", "max": 100, "unit": "C", "warn": 80, "critical": 90, "badge": "lc:e186" }
}
```

The panel shows the value in the gauge's color, amber from `warn` and red from `critical` (*Amber from* and *Red from* in the editor). `icon` is what the gauge belongs to and the optional `badge` is what it measures. Formats are `int`, `ghz`, `gb`, `rate`, `uptime`, `clock` and `live`; `scale: "log"` suits network rates, and `percent_key` fills the icon from another value than the one shown.

| Source | Needs | Provides |
|---|---|---|
| Windows | Nothing | CPU load, RAM, disk, network, uptime, GPU load, VRAM, CPU clock |
| Graphics driver | Nothing (AMD through ADL, NVIDIA through `nvidia-smi`) | GPU temperature, power, fan speed, clock |
| Libre Hardware Monitor | Free download, administrator rights | Temperatures, CPU and GPU power, fan speed, clocks |
| HWiNFO | Running with shared memory enabled (`host\Enable-HWiNFO.ps1`, as administrator, turns it on) | Sensor readings when Libre Hardware Monitor is not running; FPS from its PresentMon sensor |

To install the optional sensor source, run `powershell -ExecutionPolicy Bypass -File tools\setup_sensors.ps1` in the Tessera folder. It downloads the official release, verifies its SHA-256, enables the remote web server on `127.0.0.1:8085` and starts it (Windows asks for confirmation once). `Tessera.cmd --sensors` then starts it at every sign-in. Until it runs, the sensor tile shows `BASIC` and the affected gauges show `--`.

### Control from scripts and AI tools

The host publishes a per-run token in `host/deck-api.local.json`; `host/deckctl.py` uses it:

```powershell
python host\deckctl.py var claude working     # labels can use $(var:claude)
python host\deckctl.py state 3 next           # set a toggle key's state
python host\deckctl.py page main status       # show a page
python host\deckctl.py press 5                # press key 5
python host\deckctl.py ok 5                   # flash key 5 green (alert 5: red)
python host\deckctl.py status                 # also: wake, dim
```

Each token is limited to 20 calls a second (bursts of 40, then `429`), and every change is logged with the caller's name.

**Claude Code.** *Connect Claude Code …* (above) wires this up. Every hook runs `deckctl adapter claude`, which reads the hook's JSON from stdin and sets `$(var:claude)` (`working`, `waiting`, `idle`, `ended`), `$(var:claude.tool)`, `$(var:claude.project)` and `$(var:claude.message)`. It always exits 0, so a stopped host never disturbs Claude Code.

**Codex.** Codex reports only finished turns through its `notify` setting. Point it at `python host\deckctl.py adapter codex` and `$(var:codex)`, `codex.project` and `codex.message` are set when a turn completes. While Codex works, a key still shows `$(agent:codex)` from process detection.

**Any other tool.** `python host\deckctl.py adapter generic NAME STATE [MESSAGE]` sets `$(var:NAME)` and `$(var:NAME.message)`. Adapters live in `host/adapters.py`.

**Your own program.** Write a [plugin](PLUGINS.md): a separate process with its own limited token that sets values, reads key presses and receives commands from a key.

### Real icons for existing keys

`host\.venv\Scripts\python.exe tools\refresh_program_icons.py` gives every program key the icon `"app"`, which the host resolves from the key's `open` action. It is a dry run by default. Add `--apply` to write the changes (the old file is kept as `profiles.backup.local.json`) or `--freeze` to store the images instead.

## Troubleshooting

Start with **More → Host log …**. It shows what the USB host does: connections, presses, actions and problems. **More → Save diagnostics** writes a file to attach to a bug report. Messages in the editor's status bar and fixes for them are in [Install](INSTALL.md#troubleshooting).

| Symptom | Fix |
|---|---|
| The panel stays black but touch works | A touch wakes a dimmed panel. If it stays black, restart the host; it wakes the backlight on connect. |
| Gauges show `--` | CPU temperature and power need Libre Hardware Monitor (`tools\setup_sensors.ps1`). FPS needs HWiNFO with PresentMon. |
| A key makes only a program's taskbar button flash | Update to 0.6.0 or later and restart the host. It then brings the window to the front. |
| A key does nothing | Check the key for a yellow dot (unfinished). **Test** the key and read the steps. Then read the host log. |
| An action list click made a key on the wrong slot | A click uses the selected slot if it is empty, else the first free one. Select the empty slot first, or drag the action to it. |
