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

## Troubleshooting

| Symptom | Fix |
|---|---|
| The panel stays black but touch works | A touch wakes a dimmed panel; if it stays black, restart the host, which also wakes the backlight on connect |
| The header says *NO PC* | The host is not running or does not own the port; start it from the tray |
| `Another Tessera host is already running` | Only one host may own the port; stop it from the tray, then start again |
| Gauges show `--` | CPU temperature and power need Libre Hardware Monitor (`tools\setup_sensors.ps1`); FPS needs HWiNFO with PresentMon |
| The editor looks out of date | Close the editor window and open it again from the tray |
| Flashing fails with *port busy* | Stop the host first; it holds the COM port |
