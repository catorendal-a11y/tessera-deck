# Tessera and SmartDeck

[SmartDeck](https://github.com/ozancs/smartdeck) (v2.5.1, GPL-3.0) is an open-source macro controller for a 5" 800 × 480
ESP32-S3 touchscreen with an Electron app for Windows. This page compares it with Tessera and records what Tessera
took from the comparison.

**What this is based on, and what it is not.** Only SmartDeck's public README and release notes could be read
(retrieved 2026-10-21). Its source code, firmware and `DOM.html` were *not* read, and none of its code was copied or
studied for implementation. SmartDeck is GPL-3.0; Tessera's features below were designed from scratch for
Tessera's own ESP-IDF/LVGL firmware and Windows host. Where SmartDeck's behaviour is described, it is as the
README states it; behaviour that was not stated is marked *not stated*.

## What SmartDeck does that Tessera did not

| SmartDeck (per its README) | In Tessera now |
|---|---|
| Timer action: countdown with notifications | **Added.** `timer` action: start, pause, resume, stop, toggle; label `$(timer:name)`, optional countdown ring, message, sound, tray notification and actions when it ends. Running timers keep counting while Tessera is closed. |
| Counter action: increment/decrement, long-press reset | **Added.** `counter` action with step, limits and wrap; reset on long press through `hold_actions`; saved across restarts. |
| Persistent device-side state, offline use (*not stated* by SmartDeck) | **Partly added.** The panel keeps the last layout in flash and shows it after a restart without the PC. Counters and timers are saved by the Windows host, not on the panel (see limits). |
| "Install Firmware" button in the app, about 60 s | **Added.** *Panel firmware …* in the editor: verified package, board and protocol check, progress, host stopped and restarted around it, application-only mode that keeps panel settings. Not run on hardware in this work. |
| Test mode (right-click → Test), works without a device | **Added as a dry run.** *Test (dry run)* explains each step, checks hotkeys, program paths, shell values and web addresses against the panel's current values, and executes nothing. |
| 100,000+ icons through Iconify | **Added, opt-in.** *Search online* in the icon library queries api.iconify.design only when pressed; the host validates the SVG and the editor turns it into a key image in the key's color. Tessera still ships 1,895 offline Lucide icons. |
| Image crop and scale editor | **Added.** Cropper with drag and zoom for still pictures; animated GIF/WebP are sent unchanged. |
| Per-button colors: background, text, icon, stroke, shadow; alignment | **Added** background, label text and outline colors per key and per toggle state. Shadow and horizontal alignment were not added. |
| Seven interface languages | **Not added, on purpose.** Tessera's interface and documentation are English only by decision of the project owner. |
| Clock and weather (the About text mentions a weather widget; no details stated) | **Added.** Ambient screen: a large clock built from brand-colored tiles, the date and, if the user picks a city, current weather from Open-Meteo. Off by default; no internet use unless weather is configured. |
| Rotary encoder with LED ring | Not applicable: Tessera targets a different board without an encoder. |
| Mouse actions, presets for creative apps | Not added; Tessera has 119 ready-made actions and 10 templates for other programs. |
| Smart upload (only changed files), serial debug monitor | Tessera already sends only changed layouts and images, and now has *Export diagnostics* instead of a live monitor. |
| Multi-action builder, undo/redo (50 steps), app-based pages, tray, sleep/wake | Already in Tessera. |

## Where Tessera is ahead

- Live gauges (CPU, GPU, VRAM, RAM, network, temperatures, power, fans) and keys that follow Windows state
  (microphone, speakers, media), with real app icons from the Windows shell.
- A pixel-faithful editor that mirrors the panel and follows it.
- Verified device identity and protocol handshake, bounded queue with back-pressure, a slow lane so a long
  command never blocks other keys, and killable commands.
- Safer imports: executable actions are listed and need approval, shell variable values are checked, credentials
  can live in environment variables.
- Plugins with scoped tokens, AI tool adapters (Claude Code hooks, Codex notify), rotating backups with restore,
  configuration versioning, and a test suite with CI.

## Limits to be honest about

- Counters and timers live in the Windows host. If the PC is off, the panel shows the last layout but timers do
  not tick and counters cannot change. A truly device-side timer would need new firmware code and a way to keep
  time without the PC; it was not built.
- The offline layout is limited to about 3.8 KB of layout text (one flash page) and is written at most once per
  ten minutes and only when the key structure changes, to spare the flash. Larger layouts are simply not kept.
- Nothing in the firmware, installer or ambient screen has been run on the physical panel in this work; they are
  covered by native LVGL rendering tests and host tests only.
