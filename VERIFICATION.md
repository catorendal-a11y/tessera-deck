# Verification

What is checked, how, and — just as important — what has **not** been checked on real hardware.

## Automatic checks (run by CI and locally)

`python -m unittest discover -s tests` (Windows, 480+ tests, no hardware needed) covers:

| Area | Tests |
|---|---|
| Configuration | validation, migration and versioning, rotating backups and restore, import review, secret redaction |
| Host engine | every bundled button, every action type, folders, toggle states, pinned keys, recursion guard |
| Reliability | bounded queue and back-pressure, slow lane and duplicate presses, stale presses, reconnect policy, killable commands, lock behaviour |
| USB protocol | handshake with a scripted serial port (accepted, other board, wrong protocol, silence, garbage), port selection |
| Security | shell and URL substitution, credentials from the environment, scoped plugin tokens, event filtering, import approval |
| Features | counters and timers (including restarts), key colors, ambient screen and weather (fake HTTP), PC state binding, long press, AI adapters, plugins (with one real example process), dry run, online icons (fake HTTP) |
| Distribution | firmware packages (checksums, board, tampering, path traversal), installer with a fake esptool, update check and verified download, diagnostics bundle (no button contents, redaction), setup and uninstall |
| Cockpit | agents, mixer and status payloads, the rail and its shortcuts, wide keys and every widget, Claude Code permission prompts (answers, time-outs, fall back to Claude's own dialog), the hook installer |
| Editor | local server security, persistence, conflicts and the static front end; headless-Chrome screenshots are used for visual review |

The native LVGL test (`tests/native`) builds the real firmware UI and model for the host, renders 1024 × 600
frames, drives touch input, and checks the image cache limit (animated images, eviction, replacement), key colors,
the ambient screen, hold events, the rail, the agents, mixer and status screens and wide keys. The firmware itself is compiled with ESP-IDF 6.1 in CI.

`python host/tessera_terminal.py --check` verifies the terminal UI, and `ruff` checks syntax errors, undefined
names and unused imports.

## Checks that need the physical panel

`python tests/hardware_smoke.py` talks to a connected panel (identity, layout push, 21 synthetic presses, boot
id stability, brightness) and **sends no hotkeys, shell commands or other actions to Windows**. It passed
against the 0.6.0 firmware on 10 November 2026 (protocol 4, 21 presses, brightness, UTF-8, stable boot id).

Also run on the real panel during the 0.6.0 work:

- every page of six profiles (16 pages, including a page of widgets) pushed by the host and acknowledged by the panel
- a Claude Code permission question answered with **Allow** on the panel
- the firmware installer updating a running panel from 0.5.2 to 0.6.0 (*Application only*)
- a key that opens a running program bringing its window to the front

The editor was walked through against a copy of a real configuration: every page, the three key tabs on every key, all 16 dialogs, pages and profiles created, renamed and deleted, drag and drop with synthetic events, undo and redo.

**Not verified on hardware** (written and tested in simulation only):

- how the widgets, the mixer faders and the status screen look and feel on the glass (they are rendered by the same UI code in the native build)
- dragging a fader or tapping a rail shortcut with a finger
- the ambient screen, key colors and the offline layout stored in flash
- the firmware installer on a new, blank board (updating a running panel from a published release has been run)
- long-press timing on the touchscreen and behaviour across USB unplug, panel reset and Windows sleep/resume
- long-session memory use of the panel

These are the first things to check after flashing a new version; see `CHANGELOG.md` for what changed.
