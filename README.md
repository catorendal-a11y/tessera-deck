<h1 align="center">
  <img alt="Tessera" src="docs/images/logo.svg" height="72">
</h1>

<p align="center">
  <strong>A DIY Stream&nbsp;Deck: turn a 7-inch ESP32-P4 touchscreen into an open-source macro deck for Windows and Linux.</strong>
</p>

<p align="center">
  The <a href="https://catorendal-a11y.github.io/tessera-deck/">website</a> shows every screen and the editor. On Linux the host needs an X11 session: <a href="docs/LINUX.md">Tessera on Linux</a>.
</p>

<p align="center">
  <img alt="Windows" src="https://img.shields.io/badge/host-Windows%2010%2F11-0078D4?logo=windows&logoColor=white">
  <img alt="Linux (X11)" src="https://img.shields.io/badge/host-Linux%20(X11)-FCC624?logo=linux&logoColor=black">
  <a href="https://aur.archlinux.org/packages/tessera-deck"><img alt="AUR package tessera-deck" src="https://img.shields.io/aur/version/tessera-deck?logo=archlinux&logoColor=white&color=1793D1"></a>
  <img alt="ESP-IDF 6.1" src="https://img.shields.io/badge/ESP--IDF-6.1-E7352C?logo=espressif&logoColor=white">
  <img alt="LVGL 9.6" src="https://img.shields.io/badge/LVGL-9.6-2C3E50">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
  <a href="https://github.com/catorendal-a11y/tessera-deck/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/catorendal-a11y/tessera-deck?color=35D07F"></a>
  <a href="https://github.com/catorendal-a11y/tessera-deck/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/catorendal-a11y/tessera-deck/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue">
</p>

<p align="center">
  <img src="docs/images/console-desk.jpg" alt="A render of the Tessera panel in its printed desk console, close up on a desk, with the main page of app keys on the screen and a monitor out of focus behind it" width="900">
</p>

Tessera is a macro deck for Windows and Linux that you build from one 7-inch touchscreen board. It has 18 touch keys for apps, hotkeys and macros, plus widgets, live PC gauges, an AI agents screen and a sound mixer. You set it up in a drag-and-drop editor. It needs no soldering, and a [printed console](#a-desk-console-to-print) holds it on the desk.

> [!IMPORTANT]
> You need one of the [supported boards](#supported-boards), a USB cable and a PC with Windows 10/11 or Linux in an X11 session. Other boards need porting. Wayland and macOS are not supported.

<p align="center">
  <img src="docs/images/promo.gif" alt="A short loop: the Tessera logo, the Windows app and the panel joined by one USB cable, a tap on Allow on the agents screen, the editor putting a Timer key on the panel, and what you need to build one" width="760">
</p>

## Supported boards

| Board | Chip and screen | State |
|---|---|---|
| [GUITION JC1060P470C](https://www.aliexpress.com/item/1005010022828767.html) | ESP32-P4, 7-inch, 1024 × 600 | The main board, about $35 to $42. Tested on hardware, with firmware in every release. |
| [Elecrow CrowPanel Advance 7.0](docs/CROWPANEL.md) | ESP32-P4, 7-inch, 1024 × 600 | Works on a contributor's board, colors and touch included. The firmware is in the releases from 1.2.0. |
| [Waveshare ESP32-S3-Touch-LCD-7](docs/S3.md) | ESP32-S3, 7-inch, 800 × 480 | Experimental. One tester has the display, touch, keys and PC actions working over native USB. |
| [Sunton ESP32-8048S070](docs/S3.md) | ESP32-S3, 7-inch, 800 × 480 | Experimental. The firmware is in the releases, but nobody has run it on the board yet. |

If you have one of the S3 boards, [tell me how it goes](https://github.com/catorendal-a11y/tessera-deck/discussions/6). [Contributing](CONTRIBUTING.md#port-to-another-board) says what a port to another board needs.

## In short

- When Claude Code asks for permission, the question shows on the panel and you touch *Allow* or *Deny* to answer. The agents screen also shows what Claude Code, Codex and ZCode are doing, since when, and in which project.
- There is no account, cloud service or subscription. Your profiles stay on your PC, and the host goes online only for features you turn on, such as the update check or the weather. [Security](SECURITY.md#what-tessera-contacts) lists every address. The panel talks to a small host on the PC over USB.
- Firmware, host and editor are open source (MIT), with over 900 automated tests, a documented serial protocol and a plugin API.
- It needs one board, which you flash from the editor without a toolchain. See [Build it or buy one?](#build-it-or-buy-one)

| Widgets on wide keys | Answer Claude Code from the panel |
|---|---|
| <img src="docs/images/panel-widgets.png" alt="Widgets on wide keys: clock, date, volume, processor, graphics card, memory, network and AI agents"> | <img src="docs/images/panel-agents.png" alt="The agents screen: Claude Code asks for permission, with Deny and Allow"> |

| Sound mixer | Live status page |
|---|---|
| <img src="docs/images/panel-mixer.png" alt="The mixer screen: faders for the speakers, three programs and the microphone"> | <img src="docs/images/panel-status.png" alt="Status page with live gauges"> |

<p align="center">
  <img src="docs/images/editor-widgets.png" alt="The editor: the rail, the keys with their page tabs, the selected key's settings and the action list" width="900">
</p>

<sub>The panel images are drawn by the firmware UI itself in a native build (`tools/render_screens.py` and `test_ui`). The agents and mixer screens show sample data. The editor images are screenshots of the real editor.</sub>

## Quick start

### Quick start on Windows

The release zip has the host and the panel firmware, so you need no build tools.

1. Unpack `tessera-host-<version>.zip` from the [latest release](https://github.com/catorendal-a11y/tessera-deck/releases/latest) and double-click `Tessera.cmd`. The first start sets everything up and puts a shortcut on the Desktop. The editor opens.
   Windows SmartScreen may warn about the download because Tessera is not code-signed. You can compare the zip's SHA-256 with `SHA256SUMS` first, as [Install](docs/INSTALL.md#download-and-verify) explains. If no Python 3.11 or newer is found, the first start installs Python 3.12 for your user with winget and accepts its license terms.
   On Linux, see [Quick start on Linux](#quick-start-on-linux) below.
2. Connect the panel with USB. The *Getting started* checklist in the editor ticks off *Host running* and *Panel connected* by itself.
3. Open **Panel → Panel firmware and updates …** and choose the included firmware. A new board needs *Full install (new or blank panel)*, then *Install anyway*. Press *Install*. More in [Install](docs/INSTALL.md).
4. Click an action in the list on the right. It becomes a new key. Fill it in on the **Look** and **Actions** tabs. Changes are saved automatically.
5. Press the key on the panel. The editor says "It works" and lights up the key.

Nothing runs in the editor. Keys run only when you press them on the panel.

### Quick start on Linux

The host runs in an X11 session. Install it in one of two ways:

- **Arch Linux:** install the [`tessera-deck`](https://aur.archlinux.org/packages/tessera-deck) package from the AUR, for example `yay -S tessera-deck`. It brings the dependencies. Start *Tessera* (the tray icon and the USB host) or *Tessera Editor* (the editor, which starts the tray too when it is not running) from the application menu, or run `tessera` and `tessera --app` in a terminal. The package keeps your profiles and logs in `~/.local/share/tessera`.
- **Any distribution:** unpack the release zip and run `./Tessera.sh`. It needs Python 3.12 or newer with `venv`, `xdotool` and `xclip`; `libpulse` (`pactl`) gives the volume actions, and a Secret Service such as GNOME Keyring stores plugin passwords. The first start creates `host/.venv` and adds the same two menu entries. The tray starts first: click its icon to open the editor, or run `./Tessera.sh --editor`.

Your user must be allowed to open serial ports: add it to the group `uucp` (Arch) or `dialout` (Debian, Ubuntu) and log in again. Then continue with step 2 above. To stop Tessera from a terminal run `killall Tessera`; `tessera --uninstall` (the package) or `./Tessera.sh --uninstall` removes the autostart and menu entries. [Tessera on Linux](docs/LINUX.md) has the details: the tray menu, what differs from Windows and what stays Windows-only.

To update later, open **Panel → Panel firmware and updates …** and press *Check for updates*. From 1.2.4 the editor updates Tessera itself from there, starts it again, and then offers the panel's firmware without another download. [Install](docs/INSTALL.md#update-the-windows-program) has the details.

## Build it or buy one?

| | Tessera | Stream Deck MK.2 | Stream Deck XL |
|---|---|---|---|
| Price | the board, about $35–42 | $149.99 | $249.99 |
| Keys | 18 per page on a 7-inch touchscreen, keys up to three slots wide | 15 physical keys | 32 physical keys |
| Live widgets, mixer, PC status, AI agents | built in | through plugins | through plugins |
| Source code | MIT | closed | closed |

You also need a USB-C cable, and a stand helps: print the [desk console](#a-desk-console-to-print) or use a small tablet stand. Tessera is glass, so you give up the feel of a real key. A key shows it is pressed as soon as your finger lands and runs its action when you lift it. Drawing the whole screen takes about 55 ms; [Verification](VERIFICATION.md#screen-speed) has the measurements. Board prices are AliExpress street prices and the Stream Deck prices are US list prices, both from November 2026, so they may have changed.

## What it does

- Four screens on the panel: your keys, the AI agents, a sound mixer and the PC's status. A side bar you arrange yourself switches between them.
- Wide keys and widgets: a key can cover two or three slots and show the clock, the date, CPU, GPU, memory, network, volume, the AI agents, your next meeting, the music that plays or a timer.
- Icons: real app icons from the PC, 1,895 Lucide icons or your own images.
- Live gauges: CPU, GPU, VRAM, RAM, disk, network, temperatures, power, fan and FPS.
- Profiles that follow the program in front. Hold Home to stay on the one you are in.
- Over 130 ready-made actions and 10 profile templates for Windows, VS Code, browsers, meetings, media, Codex, Claude Code and ZCode.
- Macros: multi-step actions, long press, double press, hold to confirm, toggle keys, counters and timers.
- Scripts and AI tools: run a script from a key, drive keys or put a message on the panel from your own scripts with the local API or `deckctl`, or add plugins (one for Home Assistant through the PC and one for OBS Studio are included) and Claude Code hooks.
- Clock screen, offline layout, auto-dim, a banner that says why a key failed, and an updater in the editor for both the program and the panel's firmware.
- Home Assistant over Wi-Fi (beta, not in the release yet): the panel joins your Wi-Fi and shows up in Home Assistant through the ESPHome integration. See [below](#home-assistant-beta).

See [all features](docs/FEATURES.md).

## Home Assistant (beta)

This is not in the release yet. On the [`esphome-beta`](https://github.com/catorendal-a11y/tessera-deck/tree/esphome-beta) branch, the panel can also join your Wi-Fi and show up in Home Assistant through the ESPHome integration. USB to Windows keeps working as before, so one panel does both.

- Keys run Home Assistant actions straight from the panel, also when the PC is off: toggle a light, start a scene or call any other action.
- Keys can follow an entity: a key can change color while a light is on, or show a value such as 21.5 °C as its label.
- Every key is also an event (press, hold, double press) for your automations, and there are entities for the backlight, the page, the Wi-Fi signal and whether the PC is connected.
- The connection is encrypted. Home Assistant discovers the panel over mDNS and asks for its key. Wi-Fi and Home Assistant stay off until you turn them on in *Panel → Wi-Fi and Home Assistant*.

The beta runs on one panel and works with aioesphomeapi, the library Home Assistant uses to talk to ESPHome devices, but it has not been tried in a full Home Assistant install yet. To try it:

1. Check out the branch and start Tessera.
2. Install the panel firmware from the branch with *Full install*. It needs the host from the same branch.
3. Open *Panel → Wi-Fi and Home Assistant*.

To go back, check out `main` again and install its firmware with *Full install*. *Update* does not work on the beta firmware, because the host on main cannot talk to it. Your profile file still loads there: it keeps the Wi-Fi and Home Assistant settings and steps, and keys skip those steps until you switch to the beta again. Main does not check the beta's limits for one page (24 Home Assistant steps and 4,096 bytes of them, pinned keys included). If you copy or pin keys with those steps on main and a page goes past them, the beta starts with an older backup instead.

Reports in [issues](https://github.com/catorendal-a11y/tessera-deck/issues) are welcome. The [design](https://github.com/catorendal-a11y/tessera-deck/blob/esphome-beta/docs/design/esphome.md) explains how it works.

## A desk console to print

<p align="center">
  <img src="docs/images/console-printed.jpg" alt="A photo of the console printed in light grey plastic, standing on a desk with the panel in it and the main page of keys on the screen" width="900">
</p>

The console in these pictures is made for the GUITION JC1060P470C in its factory housing (the `_Y` variant). It has been printed, and that panel fits it perfectly. A second console holds the bare Elecrow CrowPanel Advance 7.0.

<p align="center">
  <img src="docs/images/console-hero.jpg" alt="The printed desk console in dark grey PLA with the panel in place, reclined 45 degrees, the main page on the screen and a USB-C cable out of the back" width="900">
</p>

| From your chair | The back | The tile mark |
|---|---|---|
| <img src="docs/images/console-user.jpg" alt="The console seen from the front at eye height, with the panel's main page"> | <img src="docs/images/console-back.jpg" alt="The back of the console: air openings, two screwdriver holes and the cable arch"> | <img src="docs/images/console-detail.jpg" alt="Close-up of the tile mark in the chin, with the printed layer lines"> |

The panel drops into a printed console that reclines it 45° and hides the cables, or into a lighter open dock. Both are drawn to print without supports. [hardware/](hardware/README.md) has the STL and STEP files, the CAD models, the print settings and how the panel is fastened. The print files are also on [Printables](https://www.printables.com/model/1921087-tessera-desk-console-for-7-inch-esp32-p4-panels-gu) and [MakerWorld](https://makerworld.com/en/models/3640174-tessera-desk-console-for-7-inch-esp32-p4-panels); MakerWorld has sliced print profiles for Bambu printers.

<sub>The first picture is a photo of the printed console. The others are rendered in Blender from the CAD model, with the panel's real screen. [`make_render.py`](hardware/scripts/make_render.py) builds the scene, saves it as [`tessera-console.blend`](hardware/render/tessera-console.blend) and renders it in 4K. See [Render the console](hardware/README.md#render-the-console).</sub>

## How it works

```mermaid
flowchart LR
    subgraph PC["PC: Windows or Linux"]
        Editor["Editor (WebView2 or a browser tab)"] -->|profiles.json| Host
        Tray["Tray app"] --> Host
        CLI["deckctl / hooks"] -->|loopback API| Host
        Sensors["Windows counters, Libre Hardware Monitor<br/>or hwmon on Linux"] --> Host
        Host["tesserad — USB host<br/>actions, profiles, sensors"]
    end
    Host <-->|"USB Serial/JTAG<br/>JSON + line protocol"| Panel["ESP32-P4 panel<br/>LVGL UI, touch"]
```

The host is the only owner of the USB port. It sends the page to the panel, receives key presses and runs the actions on the PC. The editor and the control API listen on `127.0.0.1` only.

## Documentation

| | |
|---|---|
| [Features](docs/FEATURES.md) | Everything Tessera does, by panel screen and editor area |
| [Install](docs/INSTALL.md) | Hardware, start options, flashing from source |
| [Tessera on Linux](docs/LINUX.md) | The tools the Linux host needs, what differs from Windows and what stays Windows-only |
| [Desk console](hardware/README.md) | Printable stands for the GUITION panel and the CrowPanel: STL, STEP, the CAD models and a Blender scene for renders |
| [Using Tessera](docs/USING.md) | Actions, labels, gauges, sensors, brightness, scripts, troubleshooting |
| [Plugins](docs/PLUGINS.md) | Write your own integration |
| [Serial protocol](docs/PROTOCOL.md) | What the host and the panel say to each other |
| [Development](docs/DEVELOPMENT.md) | Project layout, tests and tools |
| [Contributing](CONTRIBUTING.md) | Reporting bugs, sending changes, porting to another board |
| [Security](SECURITY.md) | Imported profiles, tokens and network use |
| [Verification](VERIFICATION.md) | What the tests cover, what was checked on a real panel and what has not been tried or measured yet |
| [ESP32-S3 boards](docs/S3.md) | The experimental port to two 800 x 480 S3 boards and what is still untested |
| [CrowPanel Advance 7.0](docs/CROWPANEL.md) | The Elecrow CrowPanel Advance 7.0 (ESP32-P4): building, flashing and what is still open |
| [Roadmap](docs/ROADMAP.md) | What is not done yet |

## Credits and license

Built with [ESP-IDF](https://github.com/espressif/esp-idf), [LVGL](https://lvgl.io), the Espressif board support
package, [cJSON](https://github.com/DaveGamble/cJSON) (MIT), [Lucide](https://lucide.dev) icons (ISC) and DejaVu fonts.
Optional sensors come from [Libre Hardware Monitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)
(MPL-2.0). Tessera is inspired by Stream Deck and [OpenDeck](https://github.com/nekename/OpenDeck) and is not
affiliated with Elgato or Corsair; Stream Deck is a trademark of its owner.

Tessera is released under the [MIT License](LICENSE). Third-party components keep their own licenses (see
`vendor/lucide/LICENSE` and the component directories).
