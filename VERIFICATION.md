# Verification

This page says what is tested automatically, what was checked on a real panel, what was tried by hand, and what has not been tried or measured.

## Tested automatically

CI and `python -m unittest discover -s tests` run over 850 tests on Windows and on Linux. Each system skips the tests written only for the other. None needs hardware.

| Area | What the tests cover |
|---|---|
| Configuration | Validation, migration and versioning, rotating backups and restore, import review, secret redaction |
| Host engine | Every bundled button, every action type, folders, toggle states, pinned keys, recursion guard |
| Reliability | Bounded queue and back-pressure, slow lane and duplicate presses, stale presses, reconnect policy, killable commands, profile lock, long-running behavior |
| USB protocol | Handshake with a scripted serial port (accepted, other board, wrong protocol, silence, garbage), port selection |
| Security | Shell and URL substitution, credentials from the environment, scoped plugin tokens, event filtering, import approval |
| Features | Counters and timers (including restarts), key colors, ambient screen and weather (fake HTTP), PC state binding, long press, hold to confirm and panel lock as the host sends them, AI adapters, plugins (with one real example process), dry run, online icons (fake HTTP) |
| Distribution | Firmware packages (checksums, board, tampering, path traversal), installer with a fake esptool, update check and verified download, diagnostics bundle, setup and uninstall |
| Cockpit | Agents, mixer and status payloads, the rail and its shortcuts, wide keys and every widget, Claude Code permission questions (answers, time-outs, fall back to Claude's own dialog), the hook installer |
| Editor | Local server security, persistence, conflicts and the static front end |

Other automatic checks:

- The native LVGL tests (`tests/native`) build the real firmware UI and model for the PC. They render 1024 x 600 frames, drive touch input and check the image cache limit, key colors, the ambient screen, hold events, the rail, the agents, mixer and status screens, wide keys and text contrast. The firmware's own touch handling for hold, lock and swipe runs there only against simulated touches.
- CI compiles the firmware for all four boards with ESP-IDF 6.1 and runs `cppcheck` on the sources.
- The editor smoke test opens the editor in a real browser and checks the deck, dialogs, focus and axe accessibility rules (CI only, see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)).
- `ruff` finds syntax errors, undefined names, unused imports and bug-prone patterns. `pip-audit` checks the host's packages.
- `python host/tessera_terminal.py --check` checks the terminal UI.

## Checked on the panel

`python tests/hardware_smoke.py` talks to a connected panel: identity, layout push, 21 synthetic presses, boot id stability, brightness and UTF-8. It sends no hotkeys, shell commands or other actions to Windows.

| Check | Firmware | Result |
|---|---|---|
| `hardware_smoke.py` (protocol 4, 21 presses, brightness, UTF-8, stable boot id) | 0.6.0, 10 November 2026 | Passed |
| Every page of six profiles (16 pages, one of widgets) pushed by the host and acknowledged | 0.6.0 | Passed |
| A Claude Code permission question answered with Allow on the panel | 0.6.0 | Passed |
| The firmware installer updating a running panel from 0.5.2 to 0.6.0 (app only) | 0.6.0 | Passed |
| A key that opens a running program brings its window to the front | 0.6.0 | Passed |
| First full install of the A/B layout (0.7.0, esptool 5.4 and again with 5.6) | 0.7.0, 13 November 2026 | Passed |
| Update over USB into the idle slot: 0.7.0 to 0.7.0, 0.7.0 to 0.8.0, then 0.8.0 to 0.8.0 four times | 0.8.0, 13 November 2026 | Passed, with two failures (below) |
| Image upload with acknowledgements (`"imgAck":1`): four 12-frame and four still icons sent with the host's own upload code, then again with the old paced upload | 0.8.0, 16 November 2026 | Passed. 0.65 s per 12-frame icon (2.78 s paced), 86 ms per still icon (0.22 s paced) |
| Offline layout: the panel reset with the host stopped | 0.10.1, 16 November 2026 | Passed. 1.4 s after the reset it showed the 18 keys of the saved layout, not the 12 built-in ones |
| Watchdog: a test build hangs the screen task, then the USB loop | 0.10.1, 16 November 2026 | Passed. The panel restarted after 6.4 s (screen) and 7.2 s (USB) and reported `task_wdt` as the reason |
| Rollback: a test build that never confirms itself and restarts 15 s after boot, installed with *Update* | 0.10.1, 16 November 2026 | Passed. After its first restart the bootloader started the previous firmware again, which kept running |
| `hardware_smoke.py` after installing 1.0.0 with *Update* | 1.0.0, 16 November 2026 | Passed |
| The editor's *Check for updates*, *Download firmware* and *Update*, from 1.2.1 to the published 1.2.3 | 1.2.3, 18 November 2026 | Passed. The package matched `SHA256SUMS`, the install took about 40 s, and the host started again and found the panel |
| `hardware_smoke.py` after that update | 1.2.3, 18 November 2026 | Passed |
| `hardware_smoke.py` from the Linux host (CachyOS, Plasma 6 on Wayland, `/dev/ttyACM0`), then every page of six profiles (15 pages) pushed by the host and acknowledged | 1.2.4, 19 November 2026 | Passed. The tray started the host again and it found the panel in 10 s |

The watchdog and rollback tests used two builds made only for that and never published. One adds a command that hangs the screen task or the USB loop. The other skips the confirmation and restarts while the new firmware is still unconfirmed. The host turns a `task_wdt` reason into a log line and a notice; that part is covered by unit tests, not by these runs. The panel runs the normal 0.10.1 build again.

Two updates over USB stopped partway with *The panel did not answer AD_OTA_DATA* on a panel that had run 0.7.0 for about four hours; it kept its old firmware, and the next tries worked. The cause is not found. Since 0.8.0 the host aborts and starts such an upload once more by itself. `hardware_smoke.py` has not been run on 0.7.0 or 0.8.0.

*Update Tessera* in the editor was run on Windows on a copy of the program that said it was 1.2.2: it downloaded the published 1.2.3 zip, wrote 362 files, left the profile file alone and brought the firmware for all four boards. The restart that follows was run in a real folder: the tray, the host and the editor came back and the panel reconnected. The two were not run as one chain, and neither has been tried on Linux.

The editor was also walked through against a copy of a real configuration: every page, the three key tabs on every key, all dialogs, pages and profiles created, renamed and deleted, drag and drop with synthetic events, undo and redo. That was before the latest editor redesign. The editor smoke test covers the new layout only in part.

Every check in this section was made on the GUITION board. The contributor of the CrowPanel Advance 7.0 build reports it working on their board: the colors look right, touch works, and most of the hotkeys and actions they tried work. An install from the editor's firmware dialog has not been tried on that board ([docs/CROWPANEL.md](docs/CROWPANEL.md)). A user runs the build for GUITION boards with a v3.x chip on a v3.2 board, with a clean picture and working touch and keys (issue #21). One tester runs the Waveshare ESP32-S3 build at a 12 MHz pixel clock; the Sunton build has not run on a board ([docs/S3.md](docs/S3.md)).

The Linux host was tested by hand by its contributor, with a CrowPanel on Arch Linux with Cinnamon (X11). The panel link and the tray had the most testing; keys, sound and sensors had less. On CachyOS with Plasma 6 (Wayland) and a Norwegian keyboard, the Wayland backend was run against a window of its own: 80 characters typed and read back (`æøå`, the AltGr symbols and the dead-key accents), Ctrl+A, the clipboard through Klipper, and finding, focusing, maximizing, minimizing and closing the window with `kdotool`. The editor window's helper was run with a test page: a download of a file the page made, onto a new and onto an existing file, and closing the window. The mouse, typing with Caps Lock on, a switch of layout and the question about unsaved changes were not tried there. Nobody has reported a run on another distribution or desktop ([docs/LINUX.md](docs/LINUX.md)). A firmware install from the editor was tried on Linux and stopped with "Host did not stop"; the cause is fixed and covered by a test that runs on Linux, but nobody has reported a finished install from the editor on Linux since.

Both desk consoles have been printed, and each panel fits its console ([hardware/README.md](hardware/README.md)).

## Screen speed

Measured on 16 November 2026 with firmware 0.10.1 and the panel connected to the host. The numbers come from the `draws` and `drawMaxMs` fields of `get_info` ([docs/PROTOCOL.md](docs/PROTOCOL.md#handshake-fields)). An update is one pass of drawing what changed and copying it into the panel's frame buffer.

| What happens | Screen updates | Slowest update |
|---|---|---|
| Nothing changes for 1.5 s | 0 | |
| A key that opens another page (pressed with `AD_PRESS`) | 1 or 2: the pressed key, then the new page | 49 to 52 ms |
| A rail button to the mixer, or back to the keys | 1 | 37 to 49 ms |
| Opening the agents screen | 1 | 55 ms |
| A working agent's text changes | 1 | 1.4 to 1.6 ms |
| Waking the dimmed panel, which draws the whole screen | 1 | 55 to 56 ms |

The screen is drawn by one thread. A test with two threads, one per core, drew a full screen in 45 ms but garbled text and icons on the panel: LVGL unpacks the compressed glyphs of every font, the icon font too, through one shared state. The touch controller is read every 15 ms. A key shows its pressed look when the finger lands and runs its action when the finger lifts, and the key flashes green or red when the host answers.

## Tried by hand on the panel

These are in daily use on the GUITION board, up to firmware 1.2.2. The maintainer has tried each one with a finger on the glass. No numbers were taken.

| Feature | What was tried |
|---|---|
| Hold to confirm | The 0.6 s hold and the filling ring |
| Panel lock | Locking, the lock badge and the 2 s hold on the logo that unlocks |
| About sheet | The long press on the logo and the brightness slider |
| Widgets, mixer faders, status screen | How they look and work on the glass |
| Fader drag and rail shortcut taps | Touch with a finger |
| Ambient screen, key colors | With the layout stored in flash |
| Installer on a blank board | A full install on a new board |
| Hold Home to lock the profile | The held *Lock profile* step on Home, and Home turning orange |

## Not tried or not measured

| What | What is unknown |
|---|---|
| Swipe right to go back | Whether the gesture works with a finger and never presses the key it starts on. It has run only against simulated touches in the native tests |
| Tap to screen | The time from a finger on the glass to the pressed look, filmed at a high frame rate |
| Touch accuracy | Missed or wrong keys when every key is tapped many times, edges included |
| Long sessions | Long-press timing, USB unplug, panel reset, Windows sleep and resume, panel memory use over days |

After flashing a new version, go through the hand-tried list first. [CHANGELOG.md](CHANGELOG.md) lists what changed.
