# Tessera on Linux

[Back to the README](../README.md)

The host runs on Linux in an **X11 session**, and in a **Wayland session on KDE Plasma or GNOME** (see [Wayland](#wayland)).
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
| PyGObject (system Python) | `python-gobject` / `python3-gi` | the themed tray menu (optional), and the tray icon on Wayland |
| libayatana-appindicator with its typelib | `libayatana-appindicator` / `gir1.2-ayatanaappindicator3-0.1` | the tray icon on Wayland (see [Wayland](#wayland)) |
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
`TESSERA_EDITOR=browser`, the editor opens in your browser instead. WebKitGTK's DMA-BUF renderer is turned off for the window, because it draws an empty window with some GPU drivers. A browser tab is not the editor's window, so then
*Quit tray* and *Quit and stop host* also stop the editor's web server. `./Tessera.sh --setup`, `--uninstall [--purge]`, `--diagnostics`, `--terminal` and `--tray`
work as in `Tessera.cmd`. *Start with the desktop* in the tray menu writes `~/.config/autostart/tessera.desktop`.

**Stopping it from a terminal:** the tray, the host and the editor name themselves `Tessera`, so `killall Tessera` (or `pkill Tessera`) stops all three without touching other Python programs.

**The tray icon:** left click opens the editor; right click shows the menu (status, profiles, brightness, *Start / Restart / Stop host*, *Quit tray*, *Quit and stop host*). The X11 tray icon has no menu of its own, so Tessera shows it itself: a native GTK menu that follows your theme, closing with Esc or a click elsewhere. GTK runs in a small helper under the *system* Python, so you need PyGObject there (`python-gobject` on Arch, `python3-gi` and `gir1.2-gtk-3.0` on Debian or Ubuntu); the virtual environment needs nothing. Without it the menu falls back to a plain `tkinter` one (`TESSERA_TRAY_MENU=tk` forces that). On Wayland the icon is a StatusNotifier one with a menu of its own, and any click opens that menu: see [Wayland](#wayland).

Your user must be allowed to open serial ports: the group `uucp` (Arch) or `dialout` (Debian, Ubuntu).

## The panel link

Boards with a USB-UART bridge (the CrowPanel, and the Sunton S3 board) restart when a program opens the port: Linux raises
DTR and RTS before the host can lower them, and those lines drive the board's reset. The host allows for it. It waits up to
10 s for the answer, then 1.5 s more while the board shows its boot screen, and it resends a damaged layout on the same
open port instead of reopening it. Expect the panel to restart once when the host starts, and again whenever the host
(re)opens the port. Do not run a serial monitor (`idf.py monitor`) at the same time: only one program can hold the port.

An *Update* over USB keeps the port open until the new firmware has answered: opening it again would restart a board
with a USB-UART bridge, and a restart before that answer brings back the old firmware. If the board leaves USB while it
restarts into the new firmware (a board on the chip's own USB, like the GUITION board, may do that), the open port
breaks. The installer then closes it, waits a little over a minute until the new firmware has kept itself, and opens
the port again to check the version. The dialog stays at 100 % meanwhile.

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
- **Remote devices** (KDE Connect): see [below](#remote-devices-kde-connect).
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
(`host/platform_linux/wayland.py`) uses these tools instead of `xdotool` and `xclip`. The session type is read from
`XDG_SESSION_TYPE`; `TESSERA_SESSION=x11` forces the X11 backend, for a session where only XWayland is wanted.

| Tool | Package (Arch) | Used for |
|---|---|---|
| `ydotool` and its daemon | `ydotool`, then `systemctl --user enable --now ydotool` | keys, typing, mouse (without it: the RemoteDesktop portal, see below) |
| `kdotool` | `kdotool-bin` (AUR) | the window in front (smart profiles), focus and window actions; KDE Plasma only |
| the Tessera extension for GNOME Shell | `./Tessera.sh --gnome-extension` (see [Windows on GNOME](#windows-on-gnome)) | the same on GNOME |
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
  wrong layout would type other characters. With one layout nothing needs asking. The RemoteDesktop portal (below)
  needs no layout, but it is only used where `ydotool` is not installed.
- **Where the layout comes from:** XWayland (`xkbcomp`), which has the compositor's own keymap. Without it the host uses
  `XKB_DEFAULT_LAYOUT` and its companions, and on Plasma the keyboard settings or the system's layout (`localectl`). When
  none of these names a layout, typing is refused with a message instead of typing with a guessed one.
- **Punctuation in a hotkey** means the key that types it: `ctrl+minus` presses the `-` key of your layout, and
  `ctrl+slash` is Ctrl+Shift+7 on a Norwegian keyboard, where `/` is Shift+7.
- **The mouse**: `moveto` lands a little off when pointer acceleration is on, because uinput has no absolute pointer.
  Choose the *Flat* acceleration profile for the ydotool device in the mouse settings to make it exact.
- **Without `ydotool`** keys, typing, mouse buttons, the wheel and relative moves go through the desktop's
  RemoteDesktop portal (`host/platform_linux/portal.py`) instead. **The desktop asks once** whether Tessera may control
  keyboard and mouse, when the first key is pressed. That key does not wait for the answer: the press fails (the host
  log says why), so answer the dialog and press the key again. The permission is kept
  (`host/remote-desktop.local.json` holds the token that restores it), so the question does not come again after a
  restart. To take the permission back, revoke it in the desktop's settings (Privacy or Applications). Deleting that
  file does not revoke it: Tessera can then no longer restore the permission and asks again at its next start, but a
  session that is running goes on. Stop the host to end the running session. The portal takes
  characters, not key positions: the layout does not matter there and any character can be typed, but `moveto` is not
  possible, because the portal only allows relative moves. `ydotool` is used whenever it is installed.
- **Next monitor** on Plasma uses KWin's own *Window to Next Screen* action.
- **The editor window** asks before it closes with changes that are not saved yet, and *Export* asks where to save.
- **The tray icon** on Plasma is the X11 one, through XWayland: Plasma shows it with `xembedsniproxy`, with the
  same GTK right-click menu as on X11 and a left click that opens the editor. On other desktops it uses StatusNotifier
  (pystray's appindicator backend) when the desktop has a StatusNotifier host. That icon has the desktop's own menu,
  and **a left click opens that menu too**: choose *Open editor* there, because this kind of icon has no click action
  of its own. `PYSTRAY_BACKEND=appindicator` gives Plasma this icon as well. It needs `libayatana-appindicator`
  with its typelib, and PyGObject for the system Python; that Python must be the same version (3.x) as the one in
  `host/.venv`, or PyGObject cannot be loaded from it. Without those the icon is the X11 one, which GNOME does not show.
  At sign-in Tessera waits up to 10 seconds for the desktop's StatusNotifier host. A desktop without a tray (GNOME) needs the *AppIndicator and KStatusNotifierItem
  Support* extension; without it Tessera says so in a notification and keeps running without an icon. Setting
  `PYSTRAY_BACKEND` yourself (`xorg` for the X11 icon) overrides the choice.
- **Other compositors** (sway, Hyprland): keys and typing work with `ydotool`, but the window functions and
  smart profiles are refused with a message until someone adds their window query. That goes in `wayland.py` next to the
  `kdotool` calls, or in a part of its own like GNOME's.

Audio, media, secrets, sensors and the launcher do not depend on the display server and work the same.

### Windows on GNOME

GNOME shows a program no other windows, so Tessera comes with a small extension for GNOME Shell
(`host/linux/gnome-extension/tessera-windows@tessera`, tried on GNOME 51). It is marked for GNOME 51 only, so an older GNOME will not enable it:

```
./Tessera.sh --gnome-extension          # copies it to ~/.local/share/gnome-shell/extensions
# sign out and in again: GNOME loads new extensions at sign-in
gnome-extensions enable tessera-windows@tessera
```

`./Tessera.sh --gnome-extension remove` (and `--uninstall`) takes it out again. While it is on, **any program of your session
can read window titles and focus, move or close windows** (`org.tessera.Windows` on the session bus); `gnome-extensions disable
tessera-windows@tessera` turns it off. Without the extension, the profile does not follow the program in front, and a key that
needs a window says what to install. A program from a Flatpak or Snap runs under another process id, so a key that names it
(by `.exe` or process name) may not find it.

The window part of a desktop is separate from the rest of the backend: `gnome_windows.py` talks to the extension, and
sway or Hyprland would add a part of their own next to it (`desktop_windows` in `wayland.py`) and change nothing else.

## Remote devices (KDE Connect)

[Remote devices](USING.md#remote-devices-kde-connect) work as on Windows. On Linux the host finds `kdeconnectd` on the session
bus, so `kdeconnectd` must run in your desktop session. The players KDE Connect shows for a paired device are that device's, not
this PC's: `$(pc:track)` and the *shuffle / repeat* action leave them out. GSConnect (the GNOME Shell extension) is a different
program with its own D-Bus names and is not supported.

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
