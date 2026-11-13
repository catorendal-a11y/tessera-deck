# Verification

This page says what is tested automatically, what was checked on a real panel, and what nobody has tried on the panel yet.

## Tested automatically

CI and `python -m unittest discover -s tests` run several hundred tests on Windows. None needs hardware.

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

- **Native LVGL tests** (`tests/native`) build the real firmware UI and model for the PC. They render 1024 x 600 frames, drive touch input and check the image cache limit, key colors, the ambient screen, hold events, the rail, the agents, mixer and status screens, wide keys and text contrast. The firmware's own touch handling for hold, lock and swipe runs there against simulated touches, not on the panel.
- **Firmware build:** CI compiles the firmware with ESP-IDF 6.1 and runs `cppcheck` on the sources.
- **Editor smoke test:** a real browser opens the editor and checks the deck, dialogs, focus and axe accessibility rules (CI only, see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)).
- **Lint and audit:** `ruff` finds syntax errors, undefined names, unused imports and bug-prone patterns. `pip-audit` checks the host's packages.
- **Terminal UI:** `python host/tessera_terminal.py --check`.

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

Two updates over USB stopped partway with *The panel did not answer AD_OTA_DATA* on a panel that had run 0.7.0 for about four hours; it kept its old firmware, and the next tries worked. The cause is not found. Since 0.8.0 the host aborts and starts such an upload once more by itself. `hardware_smoke.py` has not been run on 0.7.0 or 0.8.0.

The editor was also walked through against a copy of a real configuration: every page, the three key tabs on every key, all dialogs, pages and profiles created, renamed and deleted, drag and drop with synthetic events, undo and redo. That was before the latest editor redesign. The editor smoke test covers the new layout only in part.

## Not verified on the panel

The code for these is written and tested in simulation. Nobody has tried them on the panel.

| Feature | What is unknown |
|---|---|
| Firmware rollback | Whether the bootloader returns to the old slot after a new firmware crashes or hangs before the host confirms it |
| Watchdog restart | Whether a hung screen or USB loop restarts the panel under real load |
| Hold to confirm | The 0.6 s hold and the filling ring with a finger on the glass |
| Panel lock | Locking, the lock badge and the 2 s hold on the logo that unlocks |
| Swipe right to go back | Whether the gesture feels right and never presses the key it starts on |
| About sheet | The long press on the logo and the saved brightness slider |
| Widgets, mixer faders, status screen | How they look and feel on the glass |
| Fader drag and rail shortcut taps | Touch with a finger |
| Ambient screen, key colors, offline layout | Behavior with the layout stored in flash |
| Installer on a blank board | A full install on a new board (updating a running panel from a published release has been done) |
| Long sessions | Long-press timing, USB unplug, panel reset, Windows sleep and resume, panel memory use over days |

Check these first after flashing a new version. [CHANGELOG.md](CHANGELOG.md) lists what changed.
