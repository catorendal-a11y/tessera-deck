# Tessera on Linux

[Back to the README](../README.md)

The host runs on Linux in an **X11 session**, and in a **Wayland session on KDE Plasma** (see [Wayland](#wayland)).
Everything the Windows host does has a Linux counterpart, except the Windows-only pieces named under
[Not on Linux](#not-on-linux). It is tested with the CrowPanel board on Arch Linux with Cinnamon (X11), and with the
GUITION board on CachyOS with Plasma 6 (Wayland); other desktops should work wherever the tools below do.

## Install

You need Python 3.12 or newer with `venv`, and these tools:

| Tool | Package (Arch / Debian, Ubuntu) | Used for |
|---|---|---|
| `xdotool` | `xdotool` | keys, typing, mouse, windows |
| `xclip` | `xclip` | the clipboard action |
| `pactl` | `libpulse` / `pulseaudio-utils` | volume, mute, mixer (PulseAudio or PipeWire) |
| a Secret Service | GNOME Keyring, KWallet or KeePassXC | plugin passwords and tokens |
| PyGObject (system Python) | `python-gobject` / `python3-gi` | the themed tray menu (optional) |
| WebKitGTK (system Python) | `webkit2gtk-4.1` / `gir1.2-webkit2-4.1` | the editor's own window (optional; without it the editor opens in your browser) |

Then, in the Tessera folder:

```
./Tessera.sh
```

The first start creates `host/.venv`, installs `host/requirements.lock` with hashes and adds two application menu entries: *Tessera* (the tray and the host) and *Tessera Editor* (the editor, which starts the tray too when it is not running). Their text is in `host/linux/*.desktop`.
After that it starts the tray icon and the USB host. Click the tray icon to open the editor; `./Tessera.sh --editor`
opens it too (`--no-browser` prints its address instead), and `./Tessera.sh --app` starts the tray and the editor together, as the *Tessera Editor* entry does.
The editor opens in a window of its own, like the Windows app: it has its own entry in the task bar, closing it closes the
editor, and the USB host keeps running in the background with the tray. A second start brings the open window to the front.
The window is GTK with WebKitGTK under the *system* Python, like the tray menu; without WebKitGTK, or with
`TESSERA_EDITOR=browser`, the editor opens in your browser instead. A browser tab is not the editor's window, so then
*Quit tray* and *Quit and stop host* also stop the editor's web server. `./Tessera.sh --setup`, `--uninstall [--purge]`, `--diagnostics`, `--terminal` and `--tray`
work as in `Tessera.cmd`. *Start with the desktop* in the tray menu writes `~/.config/autostart/tessera.desktop`.

**Stopping it from a terminal:** the tray, the host and the editor name themselves `Tessera`, so `killall Tessera` (or `pkill Tessera`) stops all three without touching other Python programs.

**The tray icon:** left click opens the editor; right click shows the menu (status, profiles, brightness, *Start / Restart / Stop host*, *Quit tray*, *Quit and stop host*). The X11 tray icon has no menu of its own, so Tessera shows it itself: a native GTK menu that follows your theme, closing with Esc or a click elsewhere. GTK runs in a small helper under the *system* Python, so you need PyGObject there (`python-gobject` on Arch, `python3-gi` and `gir1.2-gtk-3.0` on Debian or Ubuntu); the virtual environment needs nothing. Without it the menu falls back to a plain `tkinter` one (`TESSERA_TRAY_MENU=tk` forces that).

Your user must be allowed to open serial ports: the group `uucp` (Arch) or `dialout` (Debian, Ubuntu).

## The panel link

Boards with a USB-UART bridge (the CrowPanel, and the Sunton S3 board) restart when a program opens the port: Linux raises
DTR and RTS before the host can lower them, and those lines drive the board's reset. The host allows for it. It waits up to
10 s for the answer, then 1.5 s more while the board shows its boot screen, and it resends a damaged layout on the same
open port instead of reopening it. Expect the panel to restart once when the host starts, and again whenever the host
(re)opens the port. Do not run a serial monitor (`idf.py monitor`) at the same time: only one program can hold the port.

If you have other USB serial devices, set `TESSERA_PORT=/dev/ttyUSB1`. Without it the host tries the Espressif and CH340
ports it finds and keeps the one that answers like a panel.

## What is different from Windows

- **Program names** have no `.exe`: `firefox`, `spotify`. A trailing `.exe` in a profile is accepted and ignored, so a
  profile written on Windows keeps matching. Claude Code and Codex are found as `claude` and `codex`.
- **The default profile** is `host/profiles.default.linux.json`, made from the Windows one by `tools/make_linux_defaults.py`:
  Windows-only keys (`ms-settings:`, `sndvol.exe`, PowerToys, `win+...` shortcuts with no Linux equivalent) are replaced
  or removed. `win` means the Super key.
- **Open** starts `.desktop` entries with `gio launch`, other targets with `xdg-open`. The program picker lists the
  entries of the application menu, with their icons (a vector icon needs `rsvg-convert`).
- **Scripts** (the *script* action) run with `python3`, `bash`, `node` and `pwsh`: `.py`, `.pyw`, `.sh`, `.js`, `.ps1`. `.bat`, `.cmd` and `.ahk` are Windows-only and give an error. *Edit script* and the tray's *Open the host log* open the file with `xdg-open`.
- **The media action** (shuffle on/off, cycle repeat) works on MPRIS players that offer it, such as Spotify and VLC; a player without it says so instead of pretending. `$(pc:shuffle)`, `$(pc:repeat)` and keys that follow shuffle or repeat show the player's state.
- **The Claude Code, Codex and ZCode profiles** of the Linux default start their tool in your terminal (`x-terminal-emulator`, `gnome-terminal`, `konsole`, `xfce4-terminal` or `xterm`, whichever is installed).
- **Volume** uses `pactl`; per-program volume (`app:firefox`) follows PulseAudio/PipeWire streams. The media session comes
  from MPRIS, so Spotify, browsers, VLC and mpv work.
- **Secrets** (settings named like a password or token) go to the system keyring, and the profile keeps only
  `$(keyring:<id>)`. Without a keyring the save fails with a message; nothing is written in plain text.
- **Sensors** come from the kernel: CPU temperature (`k10temp`, `coretemp`), AMD GPUs (`amdgpu`), NVIDIA through `nvidia-smi`,
  and Intel RAPL power where it is readable.
- **Window actions** (`maximize`, `topmost`, `next_monitor` ...) need a window manager that follows the EWMH standard
  (Cinnamon, GNOME, KDE, Xfce, i3 ...). `xprop` is used to read the current state when you have it.
- **The idle clock** goes by the panel alone. Keyboard and mouse activity is not read on Linux yet, so the clock can come on while you work on the PC.
- **Screen lock** is read from logind and the desktop's screensaver, to dim the panel; like on Windows it does not stop actions.

## Wayland

Wayland has no common way for a program to send keys or look at windows, so the Wayland backend
(`host/platform_linux/wayland.py`) uses these tools instead of `xdotool` and `xclip`:

| Tool | Package (Arch) | Used for |
|---|---|---|
| `ydotool` and its daemon | `ydotool`, then `systemctl --user enable --now ydotool` | keys, typing, mouse |
| `kdotool` | `kdotool-bin` (AUR) | the window in front (smart profiles), focus and window actions; KDE Plasma only |
| `wl-copy` | `wl-clipboard` | the clipboard action (without it Plasma's Klipper is used) |

Your user needs write access to `/dev/uinput` for `ydotoold` (the `input` group, or the package's udev rule).

- **Typing follows your keyboard layout.** `ydotool` sends key positions, so the host reads the session's layout
  (`host/platform_linux/xkb.py`, through libxkbcommon) and presses the right keys: `@` is AltGr+2 on a Norwegian keyboard and
  Shift+2 on a US one. `~`, `^` and accented letters go through the dead keys. A character your layout has no key for
  is refused before anything is typed; put it on the clipboard and paste it instead. Caps Lock does not change the case
  of typed text: its state is read from the keyboard's LED, and a keyboard with no such LED is taken as having the lock off.
- **More than one layout:** the one in use is asked before every key or text. Plasma and sway tell, and Hyprland in
  builds from September 2025 on (`active_layout_index` in `hyprctl devices -j`). GNOME, older Hyprland and other
  desktops do not: there typing is refused with a message while the session has more than one layout, because the
  wrong layout would type other characters. With one layout nothing needs asking.
- **Where the layout comes from:** XWayland (`xkbcomp`), which has the compositor's own keymap. Without it the host uses
  `XKB_DEFAULT_LAYOUT` and its companions, and on Plasma the keyboard settings or the system's layout (`localectl`). When
  none of these names a layout, typing is refused with a message instead of typing with a guessed one.
- **Punctuation in a hotkey** means the key that types it: `ctrl+minus` presses the `-` key of your layout, and
  `ctrl+slash` is Ctrl+Shift+7 on a Norwegian keyboard, where `/` is Shift+7.
- **The mouse**: `moveto` lands a little off when pointer acceleration is on, because uinput has no absolute pointer.
  Choose the *Flat* acceleration profile for the ydotool device in the mouse settings to make it exact.
- **Next monitor** uses KWin's own *Window to Next Screen* action.
- **The editor window** asks before it closes with changes that are not saved yet, and *Export* asks where to save.
- **The tray icon** goes through XWayland and Plasma's `xembedsniproxy`, with the same GTK right-click menu as on X11.
- **Other compositors** (GNOME, sway, Hyprland): keys and typing work with `ydotool`, but the window functions and
  smart profiles are refused with a message until someone adds their window query. That goes in `wayland.py` next to the
  `kdotool` calls.

Audio, media, secrets, sensors and the launcher do not depend on the display server and work the same.

## Not on Linux

Libre Hardware Monitor and HWiNFO (`--sensors`), the Windows Store app list, and the Windows firewall and scheduled-task
scripts in `tools/`.

## For developers

The host has three layers. Shared code (validation, the engine, the editor) names no operating system API. What differs
lives in one package per system: `host/platform_windows/` (input and windows, Core Audio and WinRT media, DPAPI secrets,
the sensor readers, program lookup and icons, the editor window, shortcuts, autostart, process flags ...) and
`host/platform_linux/` (`x11.py`, `audio.py`, `media.py`, `secrets.py`, `programs.py`, `sensors.py`, `session.py`,
`desktop_entries.py`, `x11_tray_menu.py` ...). `host/input_common.py` holds the vocabulary both share (key names, operation
lists, program matching). `host/desktop.py` and `host/system_audio.py` hand the rest of the host the Windows or the Linux
functions.

`tests/test_platform_windows.py` checks that every Windows module imports on any system, and that shared modules call no
Windows API. The tests in `tests/test_*_linux.py` run the X11 backend against a private Xvfb server and never touch your
desktop or your keyring.

The Linux-only entries of `host/requirements.lock` were added by hand with `sys_platform == "linux"`; the Windows-only
ones carry `sys_platform == "win32"`. After `pip-compile` on Windows, add them again (see CONTRIBUTING.md).
