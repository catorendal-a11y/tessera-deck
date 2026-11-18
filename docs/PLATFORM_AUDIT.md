# Tessera platform-separation audit

Audit of the Windows/Linux split on branch `platform-windows`, updated after the refactoring (steps 1-8 are done and
committed). Everything below was checked on Linux only: reading the code, import probes, ruff and the test suite
(931 tests, 34 skipped, under Xvfb). Nothing was run on Windows, and the new Linux CI job has not run on a runner. A
Linux pass is not Windows evidence.

## 1. Architecture now

- **`platform_support.py`** is the only reader of `sys.platform`. It exposes `NAME`, `IS_WINDOWS`, `IS_LINUX` and
  `load('module')`, which returns `platform_<system>.module`. Any other system raises `UnsupportedPlatform` at import,
  so the host does not start on macOS or BSD.
- **`platform_windows/` and `platform_linux/`** have modules of the same name with the same functions: `audio`,
  `media`, `input`, `session`, `filelock`, `autostart`, `secrets`, `shortcuts`, `shell`, `programs`, `icons`,
  `editor_window`, `dialogs`, `tray`, `processes`, `files`, `process_flags`, `sensors`, `regional`, `labels`.
  `labels` holds the constants the shared code reads (program-name rule, default port, wording, venv names ...).
  `DesktopBackend` (X11, Wayland, none) is still the only class-based interface; the rest are function modules whose
  names are kept in step by a parity test.
- **Shared modules** call `load(...)`, or import `IS_WINDOWS` / `IS_LINUX`, instead of testing `os.name` or
  `sys.platform`. `desktop.py` and `system_audio.py` keep explicit import blocks because they re-export fixed names.
- **Tests:** `tests/platform_marks.py` gives `@windows_only` / `@linux_only` (and module versions). Unmarked tests run
  everywhere. `tests/test_platform_support.py` has the selector test, the parity test, the layering guards and an
  isolation test that imports every shared module with the other system's package blocked.
- **CI:** `host-linux` (Ubuntu, Xvfb, Python 3.11 and 3.14) was added next to the Windows jobs.

## 2. Original findings and their state

### Critical
| # | Finding | State |
|---|---|---|
| C1 | `desktop.py`, `system_audio.py`: `else` silently loaded the Windows code on any non-Linux system | Fixed. The selector raises `UnsupportedPlatform`; tested with a faked `darwin`. |
| C2 | CI ran on Windows only | Fixed: the `host-linux` job runs on Python 3.11 and 3.14. |

### High: platform logic in shared modules (about 60 inline checks in about 25 files)
| Area | State |
|---|---|
| Autostart (`deck_control.py`) | Fixed: `autostart` module on both sides. |
| Instance lock and session (`host_runtime.py`) | Fixed: `filelock` and `session` modules; `fcntl` left shared code. |
| Secrets (`secrets_store.py`) | Fixed: `secrets.seal` / `unseal`. The profile format is unchanged. |
| Program list, details, `.lnk`, editor window (`tessera_app.py`) | Fixed: `shell`, `programs.describe`, `editor_window`. The Store-app names moved to `platform_windows`. |
| Tray, first-run question, setup, shortcuts, messages | Fixed: `tray`, `dialogs`, `shortcuts`, `labels`. |
| Kill, spawn options, open, edit, beep (`action_runner.py`, `plugins.py`, `tesserad.py`, `daemon_ticks.py`) | Fixed: `processes`. |
| Private token file (`control_api.py`) | Fixed: `files.make_private`. |
| Sensors, GPU readers, disk, program icons, clock | Fixed: `sensors`, `icons`, `regional`. The Libre Hardware Monitor HTTP reader is shared (`lhm_reader.py`). |
| Program-name rule, script types, default port, serial reset, profile default, venv names, plugin environment | Fixed: constants in `labels`. |

### Medium
| # | Finding | State |
|---|---|---|
| M1 | No shared interface for the function modules | Handled by a parity test (names, required-parameter count, constants and their types). No Protocol classes, by decision. |
| M2 | `platform_linux/input.py` imported `platform_windows` | Fixed; a test forbids either package importing the other. |
| M3 | `filelock.py` could not be imported off Windows | Fixed: `msvcrt` is imported lazily; Linux has its own `filelock`. |
| M4 | Duplicate `IS_WINDOWS` / `LINUX` constants | Fixed: one definition in `platform_support`. |
| M5 | Shared modules imported `platform_windows.process_flags`; `action_preview` and `tesserad` imported `platform_windows` at the top level | Fixed. **The isolation test found one leak the audit had missed:** `tesserad.py` imported `platform_windows.input` at the top level, so a Linux start loaded Windows code. |
| M6 | `platform_windows/audio.py` and `media.py` import shared `pc_state` | Left as is: platform to shared, no cycle (it imports on both systems). |

### Low
| # | Finding | State |
|---|---|---|
| L1 | `platform_windows/*` still carry `os.name != 'nt'` / `IS_WINDOWS` guards | Left on purpose. They keep the modules importable anywhere. |
| L2 | Platform-conditional user-facing strings | Fixed for the tray, setup and validation messages (`labels`). |
| L3 | No note on adding a system | Added to `docs/DEVELOPMENT.md` ("Platforms"). |

## 3. What still names a platform in shared code

All of it is behind the selector, in lazy imports or fixed-name facades:

- `desktop.py` (input names) and `system_audio.py` (audio and media names): explicit `if IS_LINUX:` import blocks.
- `host_runtime.py`: `filelock()` and `session_locked()` choose between two lazy imports.
- `deck_control.startup_line()`: a Windows-only helper that only the tests call.
- `tessera_app.py`: the diagnostics bundle lists both platform folders.
- `input_common.py` re-exports `IS_WINDOWS` for the modules and tests that import it from there.

## 4. Known differences and risks (not fixed)

- **Parameter names differ between the platforms** (`process_name` / `process_name_`, `bring_to_front(user32, hwnd)` /
  `(_unused, window)`). The Linux functions also take optional test hooks (`run`, `now`, `reader`). The parity test
  compares only the number of required parameters. Cosmetic.
- **Linux plugins keep only `PATH`, `TEMP` and `TMP`** of the host environment (no `HOME`, `LANG`, `DISPLAY`). The old
  list was Windows-only. The effective Linux set was kept as it was, so a plugin that needs `HOME` could fail. This
  may be a bug.
- **The Linux clock is always 24 h** (the desktop locale is not read). Unchanged behaviour.
- **Preview of a script on Linux** now says a `.bat` is not supported on Linux; before, it fell back to the Windows
  logic.
- **A Windows-only helper still sits on `Tessera`'s public surface** (`deck_control.startup_line`).
- **Unmarked tests may still assume one system.** Only tests that failed on Linux were marked. Nobody has checked
  whether unmarked tests assume Linux behaviour on Windows.
- **The Windows side is unverified.** The moved and new Windows code was never executed: `processes`, `files`,
  `programs.describe`, `secrets.seal` / `unseal`, `labels`, `sensors`, `icons.program_icon_image`, the `open_target`
  rewrite and the `process_flags` path.

## 5. Tests

| Test | What it covers |
|---|---|
| Selector | `detect()` for `win32`, `linux`, `linux2`; `darwin`, `freebsd14`, `cygwin`, `aix` are refused; a subprocess with `sys.platform = 'darwin'` fails to import `desktop` with the message. |
| Parity | Every module and name the shared code uses exists on both sides with the same required parameters; both sides have the same constants of the same type. |
| Isolation | Every shared module imports with the other system's package blocked. |
| Layering | No `fcntl` in shared modules; neither platform package imports the other; no Windows API names in shared modules (the older regex guard). |
| Platform marks | Windows tests skip on Linux, Linux tests skip on Windows. |
| Launcher guard | `HostCase` replaces the two real launchers, so a test cannot open a real file or program. This came from a test that opened `deck.local.log` in an editor. |

## Commits

1. `e78fdc7` selector, Linux file lock, explicit error on unsupported systems
2. `6cc58e9` platform marks and the Linux CI job
3. `48ed68b` tests no longer open real files
4. `7d98afd` autostart
5. `de1bfeb` program list, editor window, secrets
6. `6d0067c` tray and setup
7. `e56eb1d` processes, file permissions, process flags
8. `e5bb189` labels, sensors, icons, regional, docs
9. `fe00167` ruff findings
