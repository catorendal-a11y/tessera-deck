# Install

[Back to the README](../README.md)

> [!IMPORTANT]
> This page is written for the main board: the **GUITION 7-inch IPS display dev board** (ESP32-P4 + ESP32-C6, 1024 × 600
> capacitive touch screen), bought from [this AliExpress listing](https://www.aliexpress.com/item/1005010022828767.html).
> The firmware runs on Espressif's ESP32-P4 Function EV Board support package, and the pin setup and screen layout
> are written for this kit. Five more boards have firmware in the releases: the Elecrow CrowPanel Advance 7.0 ([CrowPanel Advance 7.0](CROWPANEL.md)) and, as an experiment, four ESP32-S3 boards ([ESP32-S3 boards](S3.md)). Those pages say what differs from the steps here. Any other board or display needs a port.

<p align="center">
  <img src="images/board.jpg" alt="The GUITION 7-inch ESP32-P4 display dev board Tessera is made for" width="420"><br>
  <sub>The GUITION board (image from the seller's listing).</sub>
</p>

## Requirements

| Part | Notes |
|---|---|
| Board | GUITION 7-inch ESP32-P4 display dev board, model JC1060P470C. Other sellers also list the board under this model number. Newer boards have chip revision v3.x and take their own package, `tessera-firmware-tessera-p4-v3-<version>.zip` (see [Flash the panel](#flash-the-panel)). |
| Display | 1024 × 600 MIPI-DSI panel (JD9165) with GT911 capacitive touch |
| Cable | USB cable from the PC to the board's USB Serial/JTAG port. No Wi-Fi is needed. |
| PC | Windows 10 or 11 and 64-bit (x64) Python 3.11 or newer; arm64 and 32-bit Python do not work. If no fitting Python is found, the first start installs Python 3.12 for your user with winget. On Linux: an X11 session and Python 3.12 or newer, see [Tessera on Linux](LINUX.md). |

## Download and verify

1. Download `tessera-host-<version>.zip` and `SHA256SUMS` from the [latest release](https://github.com/catorendal-a11y/tessera-deck/releases/latest).
2. Compare the zip's SHA-256 with its line in `SHA256SUMS`. The two hashes must match (letter case does not matter).

   ```powershell
   Get-FileHash .\tessera-host-v1.2.12.zip -Algorithm SHA256
   Get-Content .\SHA256SUMS
   ```

3. Optional, with the GitHub CLI: `gh attestation verify tessera-host-v1.2.12.zip --repo catorendal-a11y/tessera-deck` checks that the release workflow built the zip.
4. Unpack the zip. It holds the host, the editor and the firmware packages in `firmware/`.

The release also has the same file as `tessera-host.zip`, without the version in its name, so one address always gives the latest: `https://github.com/catorendal-a11y/tessera-deck/releases/latest/download/tessera-host.zip`. The README's terminal commands use it. `SHA256SUMS` lists both names with the same checksum.

Windows SmartScreen may warn about the download. Tessera is not signed with a paid code-signing certificate (a signed
installer is on the [roadmap](ROADMAP.md)), so the warning says nothing about this file. If the hashes match, choose
*More info* and *Run anyway*.

## First 5 minutes

1. Double-click `Tessera.cmd`. The tray icon, the USB host and the editor start.
2. Plug the panel into the PC's USB port with the cable on the panel's USB Serial/JTAG port. On the GUITION board that is the USB-C port marked *Full-speed Type-C* (number 7 in GUITION's interface drawing); the *High-speed Type-C* port next to it gives the panel power but no link to the PC.
3. A new panel needs firmware. Open **Panel → Panel firmware and updates …**, and wait a few seconds while the dialog looks at the USB port. It names the chip it found and chooses *Full install (new or blank panel)*. If only one board has that chip, its package is already chosen; otherwise choose your board in the list. Press *Install*.
4. Follow the *Getting started* checklist in the editor. It ticks each step off by itself: Host running, Panel connected, Firmware up to date, Put an action on a key, Press it on the panel.
5. For the fourth step, click an action in the action list on the right. It makes a new key. Fill it in on the **Look** and **Actions** tabs.
6. Press the key on the panel. The editor says "It works" and lights up the key.

The editor does not run keys; they run only when you press them on the panel. The one exception is **Test** on a key and then *Run now on this PC*.

## First run

The first start of `Tessera.cmd` shows numbered progress lines (1/3 to 3/3). It

- finds 64-bit (x64) Python 3.11 or newer, or installs x64 Python 3.12 with winget;
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

On Linux, `./Tessera.sh` takes the same options, apart from `--sensors` and `--sensors-off`. [Tessera on Linux](LINUX.md) has the rest.

## Flash the panel

Use **Panel → Panel firmware and updates …** in the editor. The installer checks the package, the board and the
protocol before it writes anything, stops the host while it writes and starts it again afterwards. Do not unplug the cable while it writes.

| Choice under *What to write* | Use it for |
|---|---|
| *Full install (new or blank panel)* | A new or blank board, and the first install of firmware with A/B slots. It writes the bootloader, the partition table and the app. |
| *Update (keeps settings)* | Every later update. It writes only the app, over the panel's own USB connection. |

Under the package list the dialog says when the panel already has that version, when the package is older than the firmware on the panel (installing it goes back), and when the folder has no package for this Tessera version. *Check for updates* then downloads it.

- A new board without Tessera firmware does not answer. The dialog then asks the chip itself what it is: esptool reads it from the ROM bootloader, and that restarts the board. On the chip's own USB (the GUITION board, the Waveshare S3 boards) the dialog does this at once. Behind a USB serial adapter (the CH340 on the CrowPanel and Sunton boards) the device could also be an Arduino or a 3D printer, so the dialog names it and asks before it restarts it. On Windows the device is then left alone after *Cancel*, and *Install* refuses it as well until you have said yes in a new look. On Linux it may restart anyway, see the next point.
- On Linux, opening the port of a USB serial adapter raises DTR and RTS (see [Tessera on Linux](LINUX.md#the-panel-link)), and a board that has those lines wired to its reset restarts: an Arduino, most 3D printer boards, and the UART panels (the CrowPanel and Sunton boards). The dialog has to open the port to see whether a panel answers. So on Linux such a device restarts before the question comes up, again at every new look, and when you choose *Install* after *Cancel*; *Cancel* only keeps esptool away from it. Unplug a 3D printer or another device on a CH340 before you open the dialog on Linux.
- The dialog shows what it found, for example `New panel on COM7: ESP32-P4 revision v3.2`, and lists only the packages for boards with that chip. An ESP32-P4 behind a USB serial adapter can only be the CrowPanel, so the dialog picks its package; there is no package yet for a CrowPanel with a v3.x chip, and the dialog says so. *Show the packages for other boards too* brings the rest back, and *Look for the panel again* repeats the look after you plug the board in. *Install* then asks once before it writes everything.
- Newer GUITION boards have an ESP32-P4 of revision v3.x, and firmware for the older v1.x chip does not start on them (the screen stays black). The dialog reads the revision and chooses the package for it. A v3.x board takes `tessera-firmware-tessera-p4-v3-<version>.zip`, an older one `tessera-firmware-<version>.zip`. If you pick the wrong one, esptool refuses it before it writes anything, and the editor says which package to use.
- The release zip includes a firmware package. The `firmware` folder of the release zip already has the packages for every board. *Check for updates* asks GitHub for the latest release and can download the package for the connected panel, or for the board the dialog found on the USB port (when it could be more than one board, the one for GUITION boards with a v1.x chip); it is kept only if its SHA-256 matches `SHA256SUMS`. You can also put the package for your board from the Releases page in the `firmware` folder and choose it in the dialog. Pick the one named for your board: apart from the CrowPanel P4, which the dialog knows by its USB serial adapter, the installer cannot tell two boards with the same chip apart before a firmware runs on the panel.
- The flash has two 6 MB app slots for rollback. If a new firmware crashes or hangs before its first handshake with the host (or before it has run for 60 s), the bootloader goes back to the previous one on the next reset. The details are in [RELEASING.md](RELEASING.md).
- On a panel with old single-slot firmware, the first update to A/B firmware must be a *Full install*. The installer says so.
- A panel with firmware this host cannot talk to, such as the Wi-Fi beta, also needs a *Full install*. The installer says so.

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

For a GUITION board with a v3.x chip (see above), build the v3 image instead. It starts from the tested v1.x `sdkconfig`, minus the chip revision options, which `boards/tessera-p4-v3.defaults` sets:

```powershell
python tools/v3_sdkconfig.py sdkconfig build/tessera-p4-v3/sdkconfig
idf.py -B build/tessera-p4-v3 -DSDKCONFIG=build/tessera-p4-v3/sdkconfig -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;boards/tessera-p4-v3.defaults" build
idf.py -B build/tessera-p4-v3 -p COMx flash
```

To update only the app and keep the bootloader, partition table and stored settings:

```powershell
python -m esptool --chip esp32p4 -p COMx -b 460800 write-flash 0xd000 build\idf6\ota_data_initial.bin 0x10000 build\idf6\tessera.bin
```

On a board with a v3.x chip, write the files from the v3 build instead. The partition layout is the same:

```powershell
python -m esptool --chip esp32p4 -p COMx -b 460800 write-flash 0xd000 build\tessera-p4-v3\ota_data_initial.bin 0x10000 build\tessera-p4-v3\tessera.bin
```

The OTA data image makes the bootloader start `ota_0` again, even if an update over USB left the other slot active.

## Update the Windows program

From version 1.2.4 the editor does it. Open **Panel → Panel firmware and updates …**, press *Check for updates* and then *Update Tessera to …*. It downloads the release's program zip, keeps it only if its SHA-256 matches `SHA256SUMS`, and unpacks it over the program folder. Your profiles, icons and backups are not in a release, so they stay where they are. Tessera then closes and starts again by itself: the tray, the host and the editor. The zip has the firmware for every board, so the same dialog then offers the panel's update without another download. A source checkout is left alone: update it with `git pull`.

To do it by hand: replace the program folder with the new `tessera-host` zip, or run `git pull` in a source checkout. Copy your data
over first: from `host/`, copy `profiles.json`, `assets/`, `backups/` and the `*.local.json` files (counters, timers,
your icon library and the panel you used last). [Releasing](RELEASING.md) lists them by name. Then check **Panel → Panel firmware and updates …** for newer firmware. The tray menu has **Help → Check for updates**. The tray can also look once a day and tell you when a new version is out. On Windows it asks once whether you want that; **Help → Check for updates automatically** switches it on or off at any time.

If you unpacked the new version to a new folder and Start with Windows was on, start the new copy once with `Tessera.cmd`. When the panel connects, its tray asks whether Start with Windows should start the new copy instead.

On Linux the steps are the same, with `./Tessera.sh`.

## Autostart

Choose **Start with Windows** in the tray menu, or tick *Start the USB host automatically when I sign in* in **Program settings** in the editor. After the panel first connects, the tray asks once whether to start with Windows. On Linux the tray entry is *Start with the desktop*.

## Uninstall

```powershell
Tessera.cmd --uninstall
```

This removes the autostart entry and the Desktop shortcut. Your profiles, icons and backups stay. Add `--purge` to
delete them too (Tessera asks you to type `YES` first). To remove the program itself, delete its folder afterwards.
If you ever ran `Tessera.cmd --sensors`, run `Tessera.cmd --sensors-off` before you delete the folder. It removes the
sign-in task that starts Libre Hardware Monitor with administrator rights, and its firewall rule. Libre Hardware
Monitor's own copy in `%ProgramFiles%\Tessera` stays: quit Libre Hardware Monitor from its icon in the notification
area, then delete that folder in File Explorer (Windows asks for administrator permission).

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
| A USB device stopped responding. | Unplug the device on the port the second line names and plug it in again. That is usually the panel, but it can be another ESP32 or CH340 board. This happens when it is pulled out while the host talks to it, after sleep, or with a loose cable. |
| The USB device found is not a Tessera panel. | Plug in the panel with its USB Serial/JTAG port (on the GUITION board, the full-speed USB-C port). On a CrowPanel, use the USB-C port marked UART. |
| The panel firmware is too old for this Tessera. | Press *Panel firmware …* and update. |
| No panel found. Check the USB cable … | Use a data cable on the board's USB Serial/JTAG port (on the GUITION board, the full-speed USB-C port, not the high-speed one), or on a CrowPanel the USB-C port marked UART. A new panel needs firmware: press *Panel firmware …*. The second line shows the host's own error. |
| The panel firmware (x) is older than Tessera (y). | Press *Update firmware …*, or *Not now*. |

More symptoms:

| Symptom | Fix |
|---|---|
| `Another Tessera host is already running` | Only one host may own the port. Stop it from the tray, then start again. |
| The rail on the panel shows *NO PC* above the clock | The host is not running or does not own the port. Start it from the tray. |
| Python is missing, older than 3.11 or not 64-bit | Install 64-bit (x64) Python 3.11 or newer from python.org and start `Tessera.cmd` again. If `host\.venv` was left half-made, delete that folder first. |
| `Tessera needs 64-bit (x64) Python on Windows` | 32-bit and arm64 Python cannot install Tessera's packages. Install x64 Python 3.11 or newer from python.org (Windows 11 on Arm runs it too), delete the folder `host\.venv` and start `Tessera.cmd` again. |
| `Tessera needs the x64 Python from python.org, not MSYS2` | `host\.venv` was made with MSYS2's Python. Tessera's packages do not install into MSYS2's Python, not even the 64-bit UCRT64 one. Install x64 Python 3.11 or newer from python.org, delete the folder `host\.venv` and start `Tessera.cmd` again. |
| The editor looks out of date | Close the editor window and open it again from the tray. |
| Flashing fails with *port busy* | Stop the host first. |
| A panel that does not answer after an update | Open the firmware dialog. It chooses *Full install* when the panel does not answer; press *Install*. |
