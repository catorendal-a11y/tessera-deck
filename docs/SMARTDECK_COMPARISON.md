# Tessera and SmartDeck

[SmartDeck](https://github.com/ozancs/smartdeck) (v2.5.1, GPL-3.0) is an open-source macro controller for a 5" 800 × 480
ESP32-S3 touchscreen with an Electron app for Windows. This page compares it with Tessera (first written for 0.7.0, action count updated for 0.8.0) and records what Tessera
took from the comparison.

**What this is based on, and what it is not.** Everything about SmartDeck below is as of 2026-10-21 (v2.5.1) and was not rechecked since. SmartDeck's four README screenshots (editor, settings, button dialog, the device), its public README, release notes (v1.0.0 to v2.5.1), file list and
issue list were read (retrieved 2026-10-21). The repository contains the panel firmware and 3D-print files; its
Windows app source is not published (its issue #1 asks for it), so the app's behaviour is known only from the README
and release notes. Firmware and library sources were *not* read, and none of its code was copied or studied for
implementation. SmartDeck is GPL-3.0; Tessera's features below were designed from scratch for
Tessera's own ESP-IDF/LVGL firmware and Windows host. Where SmartDeck's behaviour is described, it is as the
README states it; behaviour that was not stated is marked *not stated*.

## What SmartDeck does that Tessera did not

| SmartDeck (per its README) | In Tessera now |
|---|---|
| Timer action: countdown with notifications | **Added.** `timer` action: start, pause, resume, stop, toggle; label `$(timer:name)`, optional countdown ring, message, sound, tray notification and actions when it ends. |
| Counter action: increment/decrement, long-press reset | **Added.** `counter` action with step, limits and wrap; reset on long press through `hold_actions`; saved across restarts. |
| Persistent device-side state, offline use (*not stated* by SmartDeck) | **Partly added.** The panel keeps the last layout in flash and shows it after a restart without the PC. Counters and timers are saved by the Windows host, not on the panel (see limits). |
| "Install Firmware" button in the app, about 60 s | **Added.** *Panel firmware and updates …* in the Panel menu: verified package, board and protocol check, progress, host stopped and restarted around it. *Update (keeps settings)* goes over the panel's own USB connection, and the bootloader rolls back to the previous firmware if a new one never reaches the host. Run on the panel from 0.5.2 to 0.6.0; see [VERIFICATION.md](../VERIFICATION.md). |
| Test mode (right-click → Test), works without a device | **Added as a dry run.** **Test** on a key explains each step and checks hotkeys, program paths, shell values and web addresses without running anything. *Run now* is the one exception: it asks first when the key runs a command, sends a web request or types text. |
| 100,000+ icons through Iconify | **Added, opt-in.** *Search online* in the icon library queries api.iconify.design only when pressed; the host validates the SVG and the editor turns it into a key image in the key's color. Tessera still ships 1,895 offline Lucide icons. |
| Image crop and scale editor | **Added.** Cropper with drag and zoom for still pictures; animated GIF/WebP are sent unchanged. |
| Per-button colors: background, text, icon, stroke, shadow; alignment | **Added** background, label text and outline colors per key and per toggle state (the *Key colors* row in the Look tab). Shadow and horizontal alignment were not added. |
| Seven interface languages | **Not added, on purpose.** Tessera's interface and documentation are English only. |
| Clock and weather (the About text mentions a weather widget; no details stated) | **Added.** Ambient screen: a large clock built from brand-colored tiles, the date and, if the user picks a city, current weather from Open-Meteo. Off by default; no internet use unless weather is configured. |
| Per-app volume ("App Audio" presets) | **Added.** The `audio` action targets `speaker`, `mic` or `app:NAME.exe` and can mute, unmute, toggle, set the volume or step it up and down. |
| Realistic typing simulation | **Added.** A `delay_ms` per character on the `text` action (0-500 ms); slow typing runs on the slow lane. |
| Weather city search with autocomplete, hourly refresh | **Partly.** Tessera searches by name and lets you choose between matching places; weather refreshes every 15 minutes. No live autocomplete and no condition icon on the clock screen. |
| Serial debug monitor | **Added as a host log.** *Host log …* in the More menu (Help group) shows a live, cleaned tail of the host's log (connections, presses, actions, problems). |
| Deep Sleep (screen and LEDs off after the dim period) | Already possible: set "Brightness when dimmed" to Off; a touch wakes the panel. |
| Global theme row (background, button, text, stroke, shadow) and a Themes menu (seen in its screenshots) | **Added.** *Key colors …* in the Panel menu sets the default background, label and outline for every key with five presets or custom colors; a key's own colors win. |
| Mouse action type (click, double-click, move, drag) | **Added** click, right/middle click, double-click, scroll, move by and move to. Drag was not added. |
| Rotary encoder with LED ring | Not applicable: Tessera targets a different board without an encoder. |
| Presets for creative apps | Not added; mouse actions exist, and Tessera has over 120 ready-made actions and 10 profile templates for other programs. |
| Smart upload (only changed files) | Tessera already sends only changed layouts and images; *Save diagnostics* in the More menu adds a support bundle. |
| Multi-action builder, undo/redo, app-based pages, tray, sleep/wake | Already in Tessera. |

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
  not tick and counters cannot change. Device-side timers are not built (see the [roadmap](ROADMAP.md)).
- The offline layout is limited to 8 KB of layout text, and the panel keeps the previous one as a backup. A layout
  over 8 KB gets a "too big" answer and is not kept.
- What has run on the physical panel, and what so far only in the native LVGL tests (the ambient screen among
  them), is listed in [VERIFICATION.md](../VERIFICATION.md).
