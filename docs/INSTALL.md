# Install

[Back to the README](../README.md)

> [!IMPORTANT]
> Tessera is made for one board: the **GUITION 7-inch IPS display dev board** (ESP32-P4 + ESP32-C6, 1024 × 600
> capacitive touch screen), bought from [this AliExpress listing](https://www.aliexpress.com/item/1005010022828767.html).
> The firmware runs on Espressif's ESP32-P4 Function EV Board support package, and the pin setup and screen layout
> are written for this kit. Other ESP32 boards or displays need a port.

<p align="center">
  <img src="images/board.jpg" alt="The GUITION 7-inch ESP32-P4 display dev board Tessera is made for" width="420"><br>
  <sub>The board Tessera is made for (image from the seller's listing).</sub>
</p>

## Requirements

| Part | Notes |
|---|---|
| Board | GUITION 7-inch ESP32-P4 display dev board, model JC1060P470C |
| Display | 1024 × 600 MIPI-DSI panel (JD9165) with GT911 capacitive touch |
| Cable | USB cable from the PC to the board's USB Serial/JTAG port. No Wi-Fi is needed. |
| PC | Windows 10 or 11 and Python 3.11 or newer. If no fitting Python is found, the first start installs Python 3.12 for your user with winget. |

## Download and verify

1. Download `tessera-host-<version>.zip` and `SHA256SUMS` from the [latest release](https://github.com/catorendal-a11y/tessera-deck/releases/latest).
2. Compare the zip's SHA-256 with its line in `SHA256SUMS`. The two hashes must match (letter case does not matter).

   ```powershell
   Get-FileHash .\tessera-host-v0.7.0.zip -Algorithm SHA256
   Get-Content .\SHA256SUMS
   ```

3. Optional, with the GitHub CLI: `gh attestation verify tessera-host-v0.7.0.zip --repo catorendal-a11y/tessera-deck` checks that the release workflow built the zip.
4. Unpack the zip. It holds the host, the editor and the firmware package in `firmware/`.

Windows SmartScreen may warn about the download. Tessera is not signed with a paid code-signing certificate (a signed
installer is on the [roadmap](ROADMAP.md)), so the warning says nothing about this file. If the hashes match, choose
*More info* and *Run anyway*.

## First 5 minutes

1. Double-click `Tessera.cmd`. The tray icon, the USB host and the editor start.
2. Plug the panel into the PC's USB port with the cable on the panel's USB Serial/JTAG port.
3. A new panel needs firmware. Open **Panel → Panel firmware and updates …**, choose the included package, choose *Full install (new or blank panel)*, tick *Install anyway* and press *Install*.
4. Follow the *Getting started* checklist in the editor. It ticks each step off by itself: Host running, Panel connected, Firmware up to date, Put an action on a key, Press it on the panel.
5. For the fourth step, click an action in the action list on the right. It makes a new key. Fill it in on the **Look** and **Actions** tabs.
6. Press the key on the panel. The editor says "It works" and lights up the key.

Nothing runs in the editor. Keys run only when you press them on the panel. **Test** on a key and then *Run now on this PC* is the one exception.

## First run

The first start of `Tessera.cmd` shows numbered progress lines (1/3 to 3/3). It

- finds Python 3.11 or newer, or installs Python 3.12 with winget;
- creates `host\.venv` and installs the packages from `host/requirements.lock`, each pinned to its SHA-256 hash;
- puts a shortcut on the Desktop;
- starts the tray icon and the editor.

Later starts skip this. Packages are installed again only when `host/requirements.lock` changes. Closing the editor
window leaves the tray icon and the USB host running. Start `Tessera.cmd` again, or choose *Open editor* in the tray
menu, to bring the editor back.

A new install starts with a small home page (volume, mute, play/pause, Explorer, Terminal, screenshot, calculator,
show desktop, lock) and the Status, Desktop, Audio and Tools folders. Your changes save by themselves to
`host/profiles.json`, which is created from `host/profiles.default.json`.

Tessera finds the panel's USB Serial/JTAG port by itself and remembers the board's USB serial number, so it follows
the board if Windows renumbers the port. Set the environment variable `TESSERA_PORT` (for example `COM7`) only if it picks the wrong port.

### Start options

| Command | What it does |
|---|---|
| `Tessera.cmd` | Tray icon, USB host and editor window |
| `Tessera.cmd --tray` | Tray icon and host only |
| `Tessera.cmd --terminal` | The terminal UI |
| `Tessera.cmd --setup` | Install the dependencies and the Desktop shortcut |
| `Tessera.cmd --diagnostics` | Write a support bundle: versions, counts and a cleaned log tail, no key contents |
| `Tessera.cmd --sensors` and `--sensors-off` | Start or stop the optional sensor source at sign-in (see [Using Tessera](USING.md#live-gauges-and-sensors)) |
| `Tessera.cmd --no-browser` | Start without opening a browser window and print the editor address |
| `Tessera.cmd --uninstall` | See [Uninstall](#uninstall) |

## Flash the panel

Use **Panel → Panel firmware and updates …** in the editor. The installer checks the package, the board and the
protocol before it writes anything, stops the host while it writes and starts it again afterwards. Do not unplug the cable while it writes.

| Choice under *What to write* | Use it for |
|---|---|
| *Full install (new or blank panel)* | A new or blank board, and the first install of firmware with A/B slots. It writes the bootloader, the partition table and the app. |
| *Update (keeps settings)* | Every later update. It writes only the app, over the panel's own USB connection. |

- **New board:** a board without Tessera firmware does not answer. The dialog then chooses *Full install* and shows *Install anyway*. Tick it. The chip type is still checked.
- **Where packages come from:** the release zip includes one. *Check for updates* asks GitHub for the latest release and can download the package; it is kept only if its SHA-256 matches `SHA256SUMS`. You can also put `tessera-firmware-<version>.zip` from the Releases page in the `firmware` folder and choose it in the dialog.
- **Rollback:** the flash has two 6 MB app slots. If a new firmware never reaches the host, the bootloader goes back to the previous one on the next reset. The details are in [RELEASING.md](RELEASING.md).
- **Old single-slot firmware:** the first update to A/B firmware must be a *Full install*. The installer says so.

### Update the panel firmware

When the panel's firmware is older than Tessera, the status bar says so and offers *Update firmware …*. *Not now*
hides the notice until the next Tessera version. Open the dialog, choose the package, choose *Update (keeps settings)* and press *Install*.

### Flash from source

Install [ESP-IDF 6.1](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32p4/get-started/index.html). Stop the
host first (*Stop host* in the tray menu); it owns the port. Then, with `COMx` as the panel's port (Device Manager
lists it under *Ports* as *USB Serial Device*):

```powershell
idf.py -B build/idf6 build
idf.py -B build/idf6 -p COMx flash          # first time: bootloader, partition table and app
```

To update only the app and keep the bootloader, partition table and stored settings:

```powershell
python -m esptool --chip esp32p4 -p COMx -b 460800 write-flash 0xd000 build\idf6\ota_data_initial.bin 0x10000 build\idf6\tessera.bin
```

The OTA data image makes the bootloader start `ota_0` again, even if an update over USB left the other slot active.

## Update the Windows program

Replace the program folder with the new `tessera-host` zip, or run `git pull` in a source checkout. Copy your data
over first: from `host/`, copy `profiles.json`, `assets/`, `backups/` and the `*.local.json` files (counters, timers,
your icon library and the panel you used last). [Releasing](RELEASING.md) lists them by name. Then check **Panel → Panel firmware and updates …** for newer firmware. The tray menu has **Help → Check for updates**.

## Autostart

Choose **Start with Windows** in the tray menu, or tick *Start the USB host automatically when I sign in* in **Program settings** in the editor. After the panel first connects, the tray asks once whether to start with Windows.

## Uninstall

```powershell
Tessera.cmd --uninstall
```

This removes the autostart entry and the Desktop shortcut. Your profiles, icons and backups stay. Add `--purge` to
delete them too (Tessera asks you to type `YES` first). To remove the program itself, delete its folder afterwards.

## Troubleshooting

Start with **More → Host log …** in the editor. **More → Save diagnostics** writes a file to attach to a bug report.
The tray has the same under **Help**. Click the LED and connection text in the top bar to open *Panel status*: it shows the host, port, firmware, Tessera version and the next step.

When something blocks you, a bar at the bottom of the editor names the cause and has a button for the fix.

| Status bar says | What to do |
|---|---|
| The editor could not start: … | Press *Reload*. If it stays, start `Tessera.cmd` again. |
| The editor lost contact with Tessera. | Press *Reload*. If it does not clear, open Tessera again. |
| Your configuration file could not be read: … | Press *Restore a backup …* and choose an earlier save. At startup Tessera restores the newest good backup itself and keeps the broken file as `profiles-unreadable.local.json`. |
| The configuration was changed in another window. | Press *Reload*. Changes made here since then are lost. |
| The USB host has stopped, so the panel does not react to presses. | Press *Start host*, or use the tray. *Show the host log* says why it stopped. Edits are still saved. The tray restarts a host that dies by itself after 5 s, 15 s, 60 s, then every 5 minutes. |
| The host could not start: … | Press *Show the host log*. |
| Another program is using the panel's USB port. | Close Arduino IDE, PuTTY, Thonny or any other serial program. The panel connects by itself. Flashing from source also needs the host stopped. |
| The USB device found is not a Tessera panel. | Plug in the panel with its USB Serial/JTAG port. |
| The panel firmware is too old for this Tessera. | Press *Panel firmware …* and update. |
| No panel found. Check the USB cable … | Use a data cable on the board's USB Serial/JTAG port. A new panel needs firmware: press *Panel firmware …*. The second line shows the host's own error. |
| The panel firmware (x) is older than Tessera (y). | Press *Update firmware …*, or *Not now*. |

More symptoms:

| Symptom | Fix |
|---|---|
| `Another Tessera host is already running` | Only one host may own the port. Stop it from the tray, then start again. |
| The rail on the panel shows *NO PC* above the clock | The host is not running or does not own the port. Start it from the tray. |
| Python is missing or older than 3.11 | Install Python 3.11 or newer from python.org and start `Tessera.cmd` again. If `host\.venv` was left half-made, delete that folder first. |
| The editor looks out of date | Close the editor window and open it again from the tray. |
| Flashing fails with *port busy* | Stop the host first. |
| A panel that does not answer after an update | Open the firmware dialog, choose *Full install*, tick *Install anyway*. |
