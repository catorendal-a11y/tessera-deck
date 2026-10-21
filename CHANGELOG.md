# Changelog

## 0.5.0

Firmware protocol 3, configuration version 2. Existing profiles load unchanged and are stamped with the new
version on the next save; the old file is kept in `host/backups`.

### Reliability and security

- The panel firmware no longer contains Wi-Fi, provisioning, SNTP or the ESP-Hosted stack; USB is the only
  transport (binary 2.43 MB → 1.92 MB). Not yet run on a physical panel.
- Verified device identity: the host asks `get_info` and checks the board id and protocol before it configures a
  port, tries other Espressif USB devices only after the remembered one, and discards key presses that arrive
  before the handshake.
- The action queue is bounded and reports a full queue (`503`) instead of dropping silently; multi-job requests
  are all-or-nothing; stale presses and presses queued before a reconnect are never replayed.
- Shell commands, HTTP requests and delays run on a bounded slow lane, so a long command no longer blocks other
  keys or the host; a button that is still running ignores a second press; commands are killed as a process
  tree on timeout or shutdown.
- Imports show every command, web request, program launch and automatic rule for approval and can be imported
  without them; variable values with shell metacharacters are refused in shell commands and percent-encoded in
  URLs; HTTP credentials can come from `$(env:NAME)` and exports replace them with such references.
- The firmware image cache counts the incoming image, evicts the least recently used images and refuses what
  cannot fit (`AD_IMG_END FULL`).
- Dependency audit in CI found eight known vulnerabilities in Pillow 12.3 (which decodes user images); Tessera now requires Pillow 13.
- Fixed: the diagnostics redaction leaked user names containing a space and `Bearer` tokens (found by its test).

### Product

- Counters and timers (saved, with labels, rings, bindings, tray notifications and end actions).
- Keys follow Windows state: microphone, speakers, media; `audio` action; `$(pc:…)` labels.
- Long-press actions; return to the previous profile after an automatic switch.
- Per-key background, label and outline colors; ambient clock screen with optional weather; the panel keeps its
  last layout without the PC.
- Editor: test (dry run), image cropper, online icon search, backups and restore, plugins, ambient settings,
  panel firmware installer with update check, diagnostics export.
- Per-app and device volume (`audio` targets `app:NAME.exe`, volume set/up/down), typing speed for `text`, a choice between matching cities, and a live *Host log* view.
- Plugins with scoped tokens and an event stream; AI tool adapters for Claude Code hooks and Codex notify.
- Portable defaults: programs are found when installed elsewhere, GPU sensors prefer the discrete card on any
  vendor.
- `Tessera.cmd --setup`, `--uninstall [--purge]`, `--diagnostics`; dependencies are synced only when
  `requirements.txt` changes.
- CI for the Windows host, firmware build and native LVGL tests; tag-driven release workflow.
