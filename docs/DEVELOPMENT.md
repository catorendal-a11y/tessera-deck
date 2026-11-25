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
main/            Panel firmware: USB console, button model, LVGL UI, fonts, image decoder
components/      Board support package for the ESP32-P4 Function EV Board (the GUITION board and the CrowPanel)
boards/          Build settings for the CrowPanel and the four S3 boards, and the S3 board support
host/            The host, for Windows and Linux
  tesserad.py          USB daemon: owns the panel, the job queue and the actions
  daemon_presses.py    Key presses: fast lane, slow lane, double taps
  daemon_display.py    Backlight, dimming, quiet hours, ambient screen
  daemon_ticks.py      Triggers, timers, plugins, sensors, configuration reload
  config_check.py      Validation of profiles.json
  config_store.py      Configuration versions and backups
  panel_serial.py      USB link: handshake, layout and image transfer
  input_common.py      The key names and operation lists every system shares
  platform_support.py  The one place that reads sys.platform; `load('name')` gives the module of this system's package
  platform_windows/    Windows-specific code (input and windows, audio, secrets, sensors, ...); platform_linux/ is its Linux counterpart
  desktop.py, system_audio.py, process_flags.py        What the shared modules import for input, sound and processes
  script_files.py, lhm_reader.py                       Script types and paths; the Libre Hardware Monitor reader
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
  system_stats.py, gpu_sources.py                      Gauge values (Windows sensor readers: platform_windows/)
  live_state.py, pc_state.py, ambient.py               Counters, timers, PC state, idle screen
  deck_assets.py       Icons and images
  editor/              Editor front end (index.html, core.js, app.js, dialogs.js, CSS)
plugins/         Plugins (example-uptime is the working reference, see PLUGINS.md)
docs/            User guides, features, protocol, plugin guide, release process, roadmap, images
tests/           Host tests, native LVGL tests, editor smoke test, hardware smoke test
tools/           Packaging, screen rendering, icon and sensor tooling
vendor/          Lucide icon pack (ISC)
hardware/        The printable desk consoles and the dock
```

## Host

Use the virtual environment that `Tessera.cmd --setup` creates in `host\.venv`. On Linux, `./Tessera.sh --setup` creates `host/.venv`; use `host/.venv/bin/python` in the commands below. The Linux tests that drive X11 start their own Xvfb server and are skipped without `Xvfb`, `xdotool`, `xterm` and `xclip`.

| Task | Command |
|---|---|
| All host and editor tests | `host\.venv\Scripts\python.exe -m unittest discover -s tests` |
| One test file | `host\.venv\Scripts\python.exe -m unittest discover -s tests -p test_host_actions.py` |
| Terminal UI self-check | `host\.venv\Scripts\python.exe host\tessera_terminal.py --check` |
| Lint | `host\.venv\Scripts\python.exe -m ruff check host tests tools plugins hardware --select E9,F,B --exclude host/.venv` |
| Coverage | `host\.venv\Scripts\python.exe -m coverage run --source=host --omit="host/.venv/*,host/tessera_terminal.py" -m unittest discover -s tests`, then `-m coverage report --fail-under=73` |
| JavaScript syntax | `foreach ($f in 'core','app','dialogs') { node --check host/editor/$f.js }` in PowerShell (`node --check` reads only its first file) |

Ruff and coverage are not in `requirements.txt`. Install them with `pip install ruff==0.17.2 coverage==7.17.0`. [CONTRIBUTING.md](../CONTRIBUTING.md) has the exact CI commands.

### Platforms

Windows code lives in `host/platform_windows/` and Linux code in `host/platform_linux/`. Shared modules never test
`os.name` or `sys.platform`: they import `IS_WINDOWS` / `IS_LINUX` or call `platform_support.load('name')`, which gives
`platform_<system>.name`. `platform_support` raises `UnsupportedPlatform` on any other system, so the host does not start
on macOS. Both packages have a module of the same name with the same functions (`autostart`, `processes`, `sensors`,
`secrets`, `shortcuts`, `labels` ...). `labels` holds the constants the shared code reads (program-name rule, default port,
the words "Windows" / "the desktop" in messages). On a system other than the one a module is
written for, the unit tests that need real files, processes or system libraries run only on their own system (Windows in CI).

To add a system: add `platform_<name>/` with the same modules, name it in `platform_support.detect`, and run
`tests/test_platform_support.py`. Its parity test lists the functions and constants the shared code uses, and its isolation
test imports every shared module with the other package blocked. [PLATFORM_AUDIT.md](PLATFORM_AUDIT.md) is the audit the split was checked against.

Tests that exercise one system's behaviour carry `@windows_only` / `@linux_only` from `tests/platform_marks.py`; the rest
run everywhere.

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

It talks to a connected panel: identity, layout push, 21 synthetic presses, boot id stability, brightness. It sends no hotkeys and runs no actions on the PC. Stop the host first. On Windows only one program can have the port open, so the test cannot open it while the host runs. On Linux it can, but then the test and the host each get only some of the panel's answers: the test fails and the host reconnects. The default port is `COM4`. `--soak-seconds` sets the length of the soak (default 20).

## Firmware

The firmware builds with ESP-IDF 6.1. The commands here build it for the GUITION board (ESP32-P4); [CrowPanel Advance 7.0](CROWPANEL.md) and [ESP32-S3 boards](S3.md) have the commands for the other boards. In an ESP-IDF 6.1 shell:

```powershell
idf.py -B build/idf6 build
python tools/package_firmware.py build/idf6 dist    # writes dist/tessera-firmware-<version>.zip
```

For a GUITION board with a v3.x chip ([INSTALL.md](INSTALL.md#flash-the-panel)), build the v3 image instead. It starts from the tested v1.x `sdkconfig`, minus the chip revision options, which `boards/tessera-p4-v3.defaults` sets:

```powershell
python tools/v3_sdkconfig.py sdkconfig build/tessera-p4-v3/sdkconfig
idf.py -B build/tessera-p4-v3 -DSDKCONFIG=build/tessera-p4-v3/sdkconfig -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;boards/tessera-p4-v3.defaults" build
python tools/package_firmware.py build/tessera-p4-v3 dist --board tessera-p4-v3
```

The first build downloads LVGL and the other components into `managed_components/` (not in git). `dependencies.lock` pins their versions. `VERSION` sets the firmware version, and a change to it reconfigures the build. The flash layout is in `partitions.csv` (two 6 MB app slots). The screen is drawn by one thread (`CONFIG_LV_DRAW_SW_DRAW_UNIT_CNT=1` in `sdkconfig.defaults`); two threads garbled text and icons, see [VERIFICATION.md](../VERIFICATION.md#screen-speed). Install a package with *Panel firmware and updates …* in the editor, or by hand as [INSTALL.md](INSTALL.md) describes.

## Native LVGL tests and render tools

The native build compiles the real firmware UI (`main/ui/ui.cpp`) and model (`main/deck_model.c`) for the PC, so you can test and look at the panel without a board. It needs CMake, a C/C++ compiler and the LVGL sources in `managed_components/`, so run the firmware build or `idf.py reconfigure` once first. On Windows, `scoop install cmake ninja mingw` covers the tools.

```powershell
cmake -S tests/native -B build/native -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/native
build\native\test_ui.exe build\previews
```

`test_ui` asserts on the model and the UI: image cache limits, key colors, the ambient screen, hold events, the rail, the agents, mixer and status screens, wide keys and text contrast. It writes 1024 x 600 frames as `.ppm` files to the folder you give. Set `TESSERA_SCREEN=800x480` to run it on the small layout of the 800 x 480 boards; CI runs both sizes.

One Python tool builds on the native build:

| Tool | What it does | Command |
|---|---|---|
| `tools/render_screens.py` | Draws every page of every profile with the real UI as PNG files, plus `all-screens.png`. It only reads the profile file and sends nothing to the panel. | `host\.venv\Scripts\python.exe tools\render_screens.py host\profiles.json build\screens build\native\render_screens.exe` |

It uses the folders in the command above when you leave the arguments out (`host/profiles.json` is the profile default).

The brand assets have their own generators, which need no native build: `tools/make_logo.py` writes `logo-mark.svg`, `logo.svg` and `logo.png` in `docs/images`, and `tools/make_icon.py` writes `host/tessera.ico` from the tray mark. Run them with `host\.venv\Scripts\python.exe` after a change to the logo.

### Image cache benchmark

`tests/cache_bench.py` measures what the image cache costs when you switch between pages that share almost no icons while live keys change. The real host (`Daemon` and `PanelSerial`) talks to `cache_bench`, a native target that runs the panel's image cache, model and UI on the PC and answers the host as the firmware does. Taps go through the LVGL touch path, so each press reaches the host as it would from the panel.

By default there are 4 pages of 18 keys. Every page shows the same 2 icons and 15 of its own, key 18 goes to the next page, and keys 15 to 17 follow a variable (two labels, and a gauge without an image). The icons are gradient pictures about the size of an imported program icon. One scenario uses still icons, the other 12-frame animations of the same pictures. A first lap through the pages fills the cache and is not timed. After it the next tap comes 1.5 s after the host sent the last page, and a live value changes every 0.5 s. A change that comes during a switch waits until the switch is done.

USB time is virtual: the bytes the host writes divided by `--link-rate` (500 kB/s by default, a guess), plus `--ack-ms` for every answer the host waits for (2 ms by default, also a guess: one USB frame each way). `cache_bench` reports `"imgAck":1` as the firmware does, so the host sends images in lines of 512 bytes and waits for the panel's answer every 2 KB. With `--old-firmware` it answers as older firmware, and the host sends lines of 160 bytes with a 10 ms pause after every 4. Paint time is measured on the PC, so it shows how much work the UI does and says nothing about how long the P4 takes. Tap-to-paint is the USB time from the tap until the panel accepts the new layout, the wait for the panel's next 40 ms UI tick, and the paint time. It leaves out the 0-20 ms the panel takes to send a press. A tap that waits behind earlier work keeps its time stamp, so the host drops it after 5 s as it would with a real panel.

```powershell
cmake --build build/native --target cache_bench
host\.venv\Scripts\python.exe tests\cache_bench.py --exe build\native\cache_bench.exe
host\.venv\Scripts\python.exe tests\cache_bench.py --exe build\native\cache_bench.exe --old-firmware
```

`--json` prints the numbers of every switch and live update. `--check` exits with 1 when a key is still blank after a switch, the host's record of the panel's images differs from the panel's cache, the host reports an error, or no switch was measured because every tap was dropped. CI runs it that way with and without `--old-firmware`. `--help` lists the options for pages, shared icons, live keys, frames, timing and link rate.

Runs on the development PC (Release build) gave:

| | Still icons | 12 frames, old firmware | 12 frames |
|---|---|---|---|
| Image size (ADI1) | 11 kB | 133 kB | 133 kB |
| Hit rate | 100 % | 12 % | 12 % |
| Evictions per switch, host and panel | 0 and 0 | 15 and 15 | 15 and 15 |
| USB per switch | 1.7 kB, 10 lines | 4.2 MB, 12,537 lines | 4.1 MB, 3,951 lines |
| Tap-to-paint, median | 22 ms | 40 s | 10 s |
| Paint time on the PC, median | 0.8 ms | 0.9 ms | 0.9 ms |
| Taps dropped, of 12 | 0 | 0 | 0 |
| Live changes in the run | 36 | 908 | 259 |
| Blank keys, re-requests, disagreements | 0 | 0 | 0 |

Still icons cost the same with old firmware, within 2 ms. They fit in the 8 MiB cache on all four pages. A 12-frame icon takes 249 kB once decoded, so the cache holds 33 of them. A page shows 17, so two pages fit and four need 62. The pages come round in turn, and by the time a page comes back its own icons are gone: every switch sends 15 images and evicts 15, with old firmware or new. The acknowledgements only make sending them cheaper. With old firmware the 10 ms pauses account for 31 of the 40 s. With acknowledgements the host sends a third of the lines and never pauses, and a switch takes 10 s: about 8 s for the bytes at 500 kB/s and 2 s for some 1,000 answers at 2 ms each. Both parts rest on the guessed link rate and round trip. On a panel over USB on Windows, the host's own upload code sent a 12-frame icon in 0.65 s with acknowledgements and 2.78 s with the old paced upload, where these guesses give about 0.67 s and 2.6 s, so the 10 s and 40 s are close. The panel's paint time on a switch was not measured. A longer run has more live changes, and the ones that come during a switch wait for it. With `--pages 2 --frames 12` both pages stay in the cache and a switch costs 1.7 kB, as with still icons. With `--pages 3 --frames 12` the hit rate is 18 % and a switch takes 9.5 s, or 37 s with old firmware.

## CI

GitHub Actions runs these on every pull request and every push to main:

| Workflow, job | What it checks |
|---|---|
| `ci.yml`, host | Lint, tests with the 73 % coverage floor, terminal check and dependency audit, on Windows with Python 3.11, 3.12 and 3.14 |
| `ci.yml`, host-linux | The tests that are not Windows-only, on Linux under Xvfb (Python 3.11 and 3.14) |
| `ci.yml`, host-lock | The tests in a clean venv installed from `host/requirements.lock`, on Windows with Python 3.11 and 3.14 |
| `ci.yml`, host-lock-linux | A clean venv installed from `host/requirements.lock` on Linux (Python 3.12), then an import of every package the first start checks for, under Xvfb |
| `ci.yml`, firmware-analysis | `cppcheck` on the firmware sources |
| `ci.yml`, firmware | Firmware build in the ESP-IDF 6.1 container, packaging, native LVGL tests at 1024 x 600 and 800 x 480, and the image cache benchmark with `--check`, with and without `--old-firmware` |
| `ci.yml`, firmware-boards | Firmware build and packaging for the CrowPanel and the four S3 boards, each with its board file |
| `editor-smoke.yml` | The editor smoke test, when `host/**` or the smoke test changes |
| `audit.yml` | `pip-audit` on the versions in `host/requirements.lock`, once on Windows and once on Linux, because each skips the packages marked for the other system. It runs when `host/requirements*` changes and every Monday |

[VERIFICATION.md](../VERIFICATION.md) says what the checks cover and what nobody has tried on the panel. [RELEASING.md](RELEASING.md) describes the release process. For design background, see [SMARTDECK_COMPARISON.md](SMARTDECK_COMPARISON.md) and [ELGATO_RESEARCH.md](ELGATO_RESEARCH.md).
