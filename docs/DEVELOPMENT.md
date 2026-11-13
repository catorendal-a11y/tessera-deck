# Development

[Back to the README](../README.md)

This page is for contributors. It covers the project layout, how the pieces talk, and how to build and test each one. To send a change, read [CONTRIBUTING.md](../CONTRIBUTING.md) as well.

## How the pieces talk

```text
Editor (browser or WebView2) --HTTP, 127.0.0.1--> host --USB serial--> panel (ESP32-P4)
Plugins and AI tools         --control API------> host
```

- The host (`tesserad.py`) is the only owner of the USB port. It sends the active page (layout, live values, images) to the panel and receives key presses.
- For each press the host runs the key's actions on the PC and answers the panel with a green or red flash.
- The editor and the control API listen on `127.0.0.1` only.
- The USB protocol is in [PROTOCOL.md](PROTOCOL.md). The host accepts the protocol numbers in `SUPPORTED_PROTOCOLS` in `host/panel_serial.py`. The firmware reports its own number from `main/protocol_version.h`.

## Project layout

```text
main/            ESP32-P4 firmware: USB console, button model, LVGL UI, fonts, image decoder
components/      Board support package for the ESP32-P4 Function EV Board
host/            Windows host
  tesserad.py          USB daemon: owns the panel, the job queue and the actions
  daemon_presses.py    Key presses: fast lane, slow lane, double taps
  daemon_display.py    Backlight, dimming, quiet hours, ambient screen
  daemon_ticks.py      Triggers, timers, plugins, sensors, configuration reload
  config_check.py      Validation of profiles.json
  config_store.py      Configuration versions and backups
  panel_serial.py      USB link: handshake, layout and image transfer
  win_input.py         Keys, mouse, foreground window and focus on Windows
  tessera_app.py       Local editor server and WebView2 window
  tessera_terminal.py  Terminal UI
  tessera_tray.py      Tray app
  deckctl.py           Command line for the control API, adapters and hooks
  control_api.py       Local API with scoped tokens and the event stream
  action_runner.py     Bounded, killable command execution
  cockpit.py           Payloads for the agents, mixer and status screens and the rail
  widgets.py           Content of the wide-key widgets
  permission.py        Claude Code permission questions on the panel
  agent_activity.py    What the AI tools are doing
  adapters.py          AI tool adapters
  claude_setup.py      Installs the Claude Code hooks
  plugins.py           Plugin manifests and lifecycle
  firmware_update.py   Firmware packages and the installer
  updates.py           Update check
  import_review.py     Import approval
  action_preview.py    Dry run (Test)
  setup_tool.py        Setup, uninstall, diagnostics, dependency sync
  system_stats.py, sensor_sources.py, gpu_sources.py   Gauge values
  live_state.py, pc_state.py, ambient.py               Counters, timers, PC state, idle screen
  deck_assets.py       Icons and images
  editor/              Editor front end (index.html, core.js, app.js, dialogs.js, CSS)
plugins/         Plugins (example-uptime is the working reference, see PLUGINS.md)
docs/            User guides, features, protocol, plugin guide, release process, roadmap, images
tests/           Host tests, native LVGL tests, editor smoke test, hardware smoke test
tools/           Packaging, screen rendering, demo GIF, icon and sensor tooling
vendor/          Lucide icon pack (ISC)
hardware/        The printable desk console
```

## Host

Use the virtual environment that `Tessera.cmd --setup` creates in `host\.venv`.

| Task | Command |
|---|---|
| All host and editor tests | `host\.venv\Scripts\python.exe -m unittest discover -s tests` |
| One test file | `host\.venv\Scripts\python.exe -m unittest discover -s tests -p test_host_actions.py` |
| Terminal UI self-check | `host\.venv\Scripts\python.exe host\tessera_terminal.py --check` |
| Lint | `host\.venv\Scripts\python.exe -m ruff check host tests tools plugins hardware --select E9,F,B --exclude host/.venv` |
| Coverage | `host\.venv\Scripts\python.exe -m coverage run --source=host --omit="host/.venv/*,host/tessera_terminal.py" -m unittest discover -s tests`, then `-m coverage report --fail-under=73` |
| JavaScript syntax | `node --check host/editor/core.js host/editor/app.js host/editor/dialogs.js` |

Ruff and coverage are not in `requirements.txt`. Install them with `pip install ruff==0.17.2 coverage==7.17.0`. [CONTRIBUTING.md](../CONTRIBUTING.md) has the exact CI commands.

The tests use fake serial ports, fake HTTP and a fake esptool. None of them needs the panel.

## Editor smoke test

`tests/editor_smoke/smoke.mjs` starts the editor on a temporary copy of `profiles.default.json` and opens it in Chromium with Playwright. It checks that the deck renders, dialogs open and give the focus back, the tab lists answer the arrow keys, and axe finds no serious accessibility problems.

CI runs it (`editor-smoke.yml`) when `host/**` or the smoke test changes. To run it yourself you need Node 22 and the host's Python packages:

```powershell
cd tests\editor_smoke
npm install
npx playwright install chromium
$env:PYTHON = "..\..\host\.venv\Scripts\python.exe"
node smoke.mjs
```

## Hardware smoke test

```powershell
host\.venv\Scripts\python.exe tests\hardware_smoke.py --port COM4
```

It talks to a connected panel: identity, layout push, 21 synthetic presses, boot id stability, brightness. It sends no hotkeys and runs no actions on the PC. Stop the host first, because only one program can hold the USB port. The default port is `COM4`. `--soak-seconds` sets the length of the soak (default 20).

## Firmware

The firmware builds with ESP-IDF 6.1 for the ESP32-P4. In an ESP-IDF 6.1 shell:

```powershell
idf.py -B build/idf6 build
python tools/package_firmware.py build/idf6 dist    # writes dist/tessera-firmware-<version>.zip
```

The first build downloads LVGL and the other components into `managed_components/` (not in git). `dependencies.lock` pins their versions. `VERSION` sets the firmware version, and a change to it reconfigures the build. The flash layout is in `partitions.csv` (two 6 MB app slots). Install a package with *Panel firmware and updates …* in the editor, or by hand as [INSTALL.md](INSTALL.md) describes.

## Native LVGL tests and render tools

The native build compiles the real firmware UI (`main/ui/ui.cpp`) and model (`main/deck_model.c`) for the PC, so you can test and look at the panel without a board. It needs CMake, a C/C++ compiler and the LVGL sources in `managed_components/`, so run the firmware build or `idf.py reconfigure` once first. On Windows, `scoop install cmake ninja mingw` covers the tools.

```powershell
cmake -S tests/native -B build/native -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/native
build\native\test_ui.exe build\previews
```

`test_ui` asserts on the model and the UI: image cache limits, key colors, the ambient screen, hold events, the rail, the agents, mixer and status screens, wide keys and text contrast. It writes 1024 x 600 frames as `.ppm` files to the folder you give.

Two Python tools build on the native build:

| Tool | What it does | Command |
|---|---|---|
| `tools/render_screens.py` | Draws every page of every profile with the real UI as PNG files, plus `all-screens.png`. It only reads the profile file and sends nothing to the panel. | `host\.venv\Scripts\python.exe tools\render_screens.py host\profiles.json build\screens build\native\render_screens.exe` |
| `tools/make_demo_gif.py` | Builds `docs/images/demo.gif` from those screens, the `test_ui` frames and the editor images in `docs/images/`. | `host\.venv\Scripts\python.exe tools\make_demo_gif.py build\screens build\previews docs\images\demo.gif` |

Run `render_screens.py` and `test_ui` before the GIF tool. Both tools use the folders in the commands above when you leave the arguments out (`host/profiles.json` is the profile default).

The brand assets have their own generators, which need no native build: `tools/make_logo.py` writes `logo-mark.svg`, `logo.svg` and `logo.png` in `docs/images`, and `tools/make_icon.py` writes `host/tessera.ico` from the tray mark. Run them with `host\.venv\Scripts\python.exe` after a change to the logo.

## CI

GitHub Actions runs these on every pull request and every push to main:

| Workflow, job | What it checks |
|---|---|
| `ci.yml`, host | Lint, tests with the 73 % coverage floor, terminal check and dependency audit, on Windows with Python 3.11, 3.12 and 3.14 |
| `ci.yml`, host-lock | The tests in a clean venv installed from `host/requirements.lock` (Python 3.11 and 3.14) |
| `ci.yml`, firmware-analysis | `cppcheck` on the firmware sources |
| `ci.yml`, firmware | Firmware build in the ESP-IDF 6.1 container, packaging, native LVGL tests |
| `editor-smoke.yml` | The editor smoke test, when `host/**` or the smoke test changes |

[VERIFICATION.md](../VERIFICATION.md) says what the checks cover and what nobody has tried on the panel. [RELEASING.md](RELEASING.md) describes the release process. For design background, see [SMARTDECK_COMPARISON.md](SMARTDECK_COMPARISON.md) and [ELGATO_RESEARCH.md](ELGATO_RESEARCH.md).
