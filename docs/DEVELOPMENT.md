# Development

[Back to the README](../README.md)

## How it works

The host is the **only owner of the USB port**. It pushes the active page (button layout, live values and
images) to the panel, receives key presses, runs the configured actions on the PC and confirms the result with a
green or red flash on the key. Everything is local: the editor and the control API listen on `127.0.0.1` only.

## Project layout

```text
main/            ESP32-P4 firmware: USB console, button model, LVGL UI, fonts, image decoder
components/      Board support package for the ESP32-P4 Function EV Board
host/            Windows host
  tesserad.py          USB daemon: the engine that owns the panel, the job queue and the actions
  daemon_presses.py    Key presses: fast lane, slow lane, double taps
  daemon_display.py    Backlight, dimming, quiet hours, ambient screen
  daemon_ticks.py      Triggers, timers, plugins, sensors, configuration reload
  config_check.py      Validation of profiles.json
  panel_serial.py      USB link: handshake, layout and image transfer
  win_input.py         Keys, mouse, foreground window and focus on Windows
  tessera_app.py       Local editor server and WebView2 window
  tessera_terminal.py  Terminal UI
  tessera_tray.py      Tray app
  deckctl.py           Command line for the control API, adapters and hooks
  control_api.py       Local API with scoped tokens and the event stream
  action_runner.py     Bounded, killable command execution
  system_stats.py      Gauge values             sensor_sources.py   Windows counters, Libre Hardware Monitor
  gpu_sources.py       Graphics driver sensors  deck_assets.py      Icons and images
  live_state.py        Counters and timers      pc_state.py   Microphone, speakers, media
  ambient.py           Idle screen line and weather     adapters.py   AI tool adapters
  plugins.py           Plugin manifests and lifecycle   config_store.py   Versions and backups
  firmware_update.py   Firmware packages and installer  updates.py   Update check
  import_review.py     Import approval      action_preview.py   Dry run
  setup_tool.py        Setup, uninstall, dependency sync
  editor/              Editor front end (HTML, JS, CSS)
plugins/         Plugins (example-uptime is a working reference)
docs/            Plugin guide, release process, SmartDeck comparison, images
tests/           Unit, editor, native render and hardware smoke tests
tools/           Packaging, icon refresh, sensor setup, screen rendering and icon font tooling
vendor/          Lucide icon pack (ISC) and ArduinoJson (MIT)
```

## Checks and tools

The native build needs a C/C++ compiler, for example `scoop install mingw`.

```powershell
host\.venv\Scripts\python.exe -m unittest discover -s tests -p test_*.py -v
host\.venv\Scripts\python.exe host\tessera_terminal.py --check

cmake -S tests/native -B build/native -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/native
build\native\test_ui.exe build\previews          # renders the real LVGL UI to images
host\.venv\Scripts\python.exe tools\render_screens.py host\profiles.json build\screens build\native\render_screens.exe   # draws every page of every profile

host\.venv\Scripts\python.exe tests\hardware_smoke.py   # talks to the panel; presses no keys on the PC
```

The hardware smoke test never sends hotkeys or runs actions on the PC. GitHub Actions runs the Windows host
tests, a lint and dependency audit, the firmware build and the native LVGL tests on every push. See
[`VERIFICATION.md`](../VERIFICATION.md) for what the checks cover and what has not been run on hardware,
[`CHANGELOG.md`](../CHANGELOG.md), [`docs/SMARTDECK_COMPARISON.md`](SMARTDECK_COMPARISON.md) and
[`ELGATO_RESEARCH.md`](../ELGATO_RESEARCH.md) for the design research.
