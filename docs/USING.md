# Using Tessera

[Back to the README](../README.md)

### Profiles, pages and actions

A **profile** holds pages; a **page** holds up to 18 keys; slot 18 is the pinned **Home** key. Folders push a page
with a *Back* key in slot 17. A key runs one or more actions in order:

| Action | What it does |
|---|---|
| `hotkey` | Press a key combination or media key |
| `text` | Type text |
| `open` | Open a program, file, folder or URL (optionally focus an already running program) |
| `shell` / `http` | Run a command or call an HTTP endpoint |
| `delay` | Wait between steps |
| `folder`, `back`, `home`, `page`, `profile` | Navigate |
| `press` | Run another key |
| `set` | Set a variable |
| `state` | Set the state of a toggle key (`next` or a state number) |
| `audio` | Mute or unmute the real microphone or speaker |
| `counter`, `timer` | Change a counter; start, stop or reset a timer |
| `mouse` | Click (left, right or middle) |
| `screen` | Show the clock, the keys, or switch between them |
| `profile_lock` | Lock or unlock automatic profile switching |
| `plugin` | Send a command to a plugin |

Labels can use `$(time)`, `$(date)`, `$(profile)`, `$(page)`, `$(profile_lock)`, `$(agent:claude)`, `$(var:name)`, `$(stat:cpu_temp)`, `$(counter:name)`, `$(timer:name)` and the live PC values `$(pc:mic)`, `$(pc:speaker)`, `$(pc:volume)`, `$(pc:track)`, `$(pc:artist)`, `$(pc:media)` and `$(pc:playing)`. `$(pc:track)` shows *No music* when nothing is playing.
In a `shell` command, put a value in double quotes (`notify.exe "$(pc:track)"`): Tessera refuses values that contain shell metacharacters, but a value may contain spaces, which would otherwise become extra arguments.
A toggle button can follow the PC instead of the presses with `"bind": "mic_muted" | "speaker_muted" | "media_playing"` (state 1 = off, state 2 = on), and the `audio` action (`target`: `mic` or `speaker`, `op`: `toggle`, `mute` or `unmute`) mutes the real device. Profiles switch
automatically with rules such as `chrome.exe`, `process:claude.exe` or `title:codex`.

### The editor

The editor is laid out like the panel. The rail on the left switches between the keys and the agents, mixer and status screens; the **+** at its foot opens the rail settings. In the middle are the profile (the large title), the page tabs and the keys. A click on a key opens its settings in three tabs:

| Tab | What it holds |
|---|---|
| **Look** | Title, icon, text size and position, and the key's size (Normal, Wide, Extra wide) |
| **Actions** | Normal or toggle key, and the steps for a press, a long press and a double press |
| **Gauge** | A live gauge and what the key is bound to |

The action list on the right has four tabs: **Basics** (hotkey, open, text and the other building blocks), **Widgets**, **Ready-made** (Windows, browser, meetings, media) and **Apps** (your installed programs and the app packs). The search looks in all of them. Drag an action to a key, or click it to add it to the selected key.

To delete a page, open **⋯ → Page settings** and tick *Delete this page*. To delete a profile, open **⋯ → Profile settings** and tick *Delete the profile*. Ctrl+Z brings either back.

### Wide keys and widgets

A key can cover two or three slots on its row: choose **Wide** or **Extra wide** under *Size*. The slots to its right must be free, and a wide key cannot run past the end of the row. In `profiles.json` this is `"span": 2` or `3`.

A wide key can show something live instead of its own title (`"live"` in `profiles.json`). Drag a widget from the **Widgets** tab, or pick it under *Shows* on a wide key:

| `live` | Shows |
|---|---|
| `clock` | The time, the weekday and date, and how far the day is |
| `date` | The date, the week number and the day of the year |
| `cpu`, `gpu` | Load with a bar, temperature, clock speed or frames per second |
| `ram` | How much memory is in use |
| `network` | Download and upload speed |
| `volume` | Speaker level, muted or not, and the microphone |
| `agents` | Which AI tools are working and which wait for you |
| `media` | The track that plays, the artist and how far it is |
| `timer:NAME` | The time left of that timer, as a ring |

A widget does nothing when pressed until you give it actions like any other key.

### Live gauges and sensors

A key becomes a gauge with a `gauge` block; the host fills in the value, how far the icon is filled and the color:

```json
{
  "label": "CPU TEMP",
  "icon": "lc:e0a9",
  "gauge": { "key": "cpu_temp", "max": 100, "unit": "C", "warn": 80, "critical": 90, "badge": "lc:e186" }
}
```

`icon` is what the gauge belongs to and the optional `badge` is what it measures. Formats are `int`, `ghz` (GHz or MHz), `gb`, `rate`, `uptime`, `clock` and `live`; `scale: "log"` suits network rates, and `percent_key` fills the icon from another value than the one shown.

| Source | Needs | Provides |
|---|---|---|
| Windows | nothing | CPU load, RAM, disk, network, uptime, GPU load, VRAM, CPU clock |
| Graphics driver | nothing (AMD through ADL, NVIDIA through `nvidia-smi`) | GPU temperature, power, fan speed, clock |
| Libre Hardware Monitor | free download, administrator rights | temperatures, CPU and GPU power, fan speed, clocks |
| HWiNFO | running with shared memory enabled | sensor readings when Libre Hardware Monitor is not running; FPS from its PresentMon sensor |

Install the optional sensor source with `tools\setup_sensors.ps1`. It downloads the official release, verifies
its SHA-256, enables the remote web server on `127.0.0.1:8085` and starts it (Windows asks for confirmation
once). `Tessera.cmd --sensors` then starts it at every sign-in. Until it runs, the sensor tile shows `BASIC` and the affected gauges show `--`.

### Brightness and auto-dim

Open **Settings** in the editor, or the tray menu. By default the panel dims to 10 % after five minutes without
a press and when Windows locks; the first touch anywhere on the screen wakes it without pressing a key. The panel
remembers the brightness across restarts. Set the values in
`profiles.json` with `"display": { "brightness": 80, "dim_after": 300, "dim_level": 10 }` (`dim_after: 0` disables it).

### Control from scripts and AI tools

The host publishes a per-run token in `host/deck-api.local.json`; `host/deckctl.py` uses it:

```powershell
python host\deckctl.py var claude working     # labels can use $(var:claude)
python host\deckctl.py state 3 next           # set a toggle key's state
python host\deckctl.py page main status       # show a page
python host\deckctl.py press 5 | ok 5 | alert 5 | wake | dim | status
```

A key can change color with a variable: `"status": { "var": "claude", "colors": { "working": "#FFB74D" } }`.
The Claude Code profile uses this on its first key.

**Claude Code.** `python host\deckctl.py hooks claude` prints the `hooks` block for `~/.claude/settings.json`
(Tessera never edits your settings itself; merge it yourself). Every hook runs `deckctl adapter claude`, which reads
the hook's JSON from stdin and sets `$(var:claude)` (`working`, `waiting`, `idle`, `ended`), `$(var:claude.tool)`,
`$(var:claude.project)` and `$(var:claude.message)` (the text of a notification, for example a permission prompt).
It always exits 0, so a stopped host never disturbs Claude Code. Check the event names against the Claude Code
hooks documentation for your version.

**Codex.** Codex reports only finished turns through its `notify` setting: point it at
`python host\deckctl.py adapter codex` and `$(var:codex)`, `codex.project` and `codex.message` are set when a turn
completes. While Codex works, the key still shows `$(agent:codex)` from process detection; Codex offers no
"working" event to read.

**Any other tool.** `python host\deckctl.py adapter generic NAME STATE [MESSAGE]` sets `$(var:NAME)` and
`$(var:NAME.message)`. Adapters live in `host/adapters.py`; adding one is a function from the tool's event to
`{variable: value}`.

**Your own program.** Write a [plugin](PLUGINS.md): a separate process with its own limited token that sets
values, reads key presses and receives commands from a key.

### Real icons for existing keys

`python tools\refresh_program_icons.py` gives every program key the icon `"app"`, which the host resolves from
the key's `open` action. It is a dry run by default; add `--apply` to write the changes (the old file is kept as
`profiles.backup.local.json`) or `--freeze` to store the images instead.

## The panel's four screens

A rail on the left of the panel switches between your keys, the AI **agents**, a sound **mixer** and the PC's **status**. Choose what the last three show under **⋯ → Panel screens …** in the editor (which agents, up to three programs for the mixer and whether the microphone is included, and which readings).

The rail itself is yours to arrange: the **+** at the foot of the editor's rail (or **⋯ → Rail …**) turns the agents, mixer and status screens on or off, puts them in order and adds up to three shortcuts that jump straight to a page of any profile. The keys are always on the rail, and it holds seven buttons at most.

To answer Claude Code's permission questions on the panel, add the hook that `python host\deckctl.py hooks claude-permission` prints to `~/.claude/settings.json`. The question then appears on the agents screen and **Allow** or **Deny** is the answer. If the panel is not connected, nobody answers within 25 seconds, or the request is too long to show in full, Claude Code shows its normal dialog; Tessera never allows anything on its own.

## Troubleshooting

| Symptom | Fix |
|---|---|
| The panel stays black but touch works | A touch wakes a dimmed panel; if it stays black, restart the host, which also wakes the backlight on connect |
| The header says *NO PC* | The host is not running or does not own the port; start it from the tray |
| `Another Tessera host is already running` | Only one host may own the port; stop it from the tray, then start again |
| Gauges show `--` | CPU temperature and power need Libre Hardware Monitor (`tools\setup_sensors.ps1`); FPS needs HWiNFO with PresentMon |
| The editor looks out of date | Close the editor window and open it again from the tray |
| A key only made a program's taskbar button flash | Fixed: the host now brings the window to the front. Restart the host if it still runs the old version |
| Flashing fails with *port busy* | Stop the host first; it holds the COM port |
