# Verification

What is checked, how, and — just as important — what has **not** been checked on real hardware.

## Automatic checks (run by CI and locally)

`python -m unittest discover -s tests` (Windows, 300+ tests, no hardware needed) covers:

| Area | Tests |
|---|---|
| Configuration | validation, migration and versioning, rotating backups and restore, import review, secret redaction |
| Host engine | every bundled button, every action type, folders, toggle states, pinned keys, recursion guard |
| Reliability | bounded queue and back-pressure, slow lane and duplicate presses, stale presses, reconnect policy, killable commands, lock behaviour |
| USB protocol | handshake with a scripted serial port (accepted, other board, wrong protocol, silence, garbage), port selection |
| Security | shell and URL substitution, credentials from the environment, scoped plugin tokens, event filtering, import approval |
| Features | counters and timers (including restarts), key colors, ambient screen and weather (fake HTTP), PC state binding, long press, AI adapters, plugins (with one real example process), dry run, online icons (fake HTTP) |
| Distribution | firmware packages (checksums, board, tampering, path traversal), installer with a fake esptool, update check and verified download, diagnostics bundle (no button contents, redaction), setup and uninstall |
| Editor | local server security, persistence, conflicts and the static front end; headless-Chrome screenshots are used for visual review |

The native LVGL test (`tests/native`) builds the real firmware UI and model for the host, renders 1024 × 600
frames, drives touch input, and checks the image cache limit (animated images, eviction, replacement), key colors,
the ambient screen and hold events. The firmware itself is compiled with ESP-IDF 6.1 in CI.

`python host/tessera_terminal.py --check` verifies the terminal UI, and `ruff` checks syntax errors, undefined
names and unused imports.

## Checks that need the physical panel

`python tests/hardware_smoke.py` talks to a connected panel (identity, layout push, 21 synthetic presses, boot
id stability, brightness) and **sends no hotkeys, shell commands or other actions to Windows**. It was last run
against the firmware before the 0.5.0 changes.

**Not verified on hardware in the 0.5.0 work** (written and tested in simulation only):

- the firmware without Wi-Fi and the ESP-Hosted stack booting and keeping the display and touch working
- the ambient screen, key colors, the offline layout stored in flash and the protocol-3 handshake
- the firmware installer writing to a real board
- long-press timing on the touchscreen and behaviour across USB unplug, panel reset and Windows sleep/resume
- long-session memory use of the panel

These are the first things to check after flashing 0.5.0; see `CHANGELOG.md` for what changed.
