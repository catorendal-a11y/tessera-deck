# Install

[Back to the README](../README.md)

> [!IMPORTANT]
> **Made for one board:** the **GUITION 7-inch IPS display dev board** (ESP32-P4 + ESP32-C6, 1024 × 600
> capacitive multi-touch screen), bought from [this AliExpress listing](https://www.aliexpress.com/item/1005010022828767.html).
> The firmware runs on Espressif's ESP32-P4 Function EV Board support package, and the pin setup and screen layout
> are written for this exact kit, so other ESP32 boards or displays will not work without porting.
> You also need a Windows 10/11 PC and a USB cable to the board's USB Serial/JTAG port.

<p align="center">
  <img src="images/board.jpg" alt="The GUITION 7-inch ESP32-P4 display dev board Tessera is made for" width="420"><br>
  <sub>The board Tessera is made for (image from the seller's listing).</sub>
</p>

## Hardware

| Part | Notes |
|---|---|
| Board | GUITION 7-inch ESP32-P4 display dev board, model JC1060P470C (ESP32-P4 + ESP32-C6) |
| Display | 1024 × 600 MIPI-DSI panel (JD9165) with GT911 capacitive touch |
| Connection | USB cable to the board's USB Serial/JTAG port — no Wi-Fi is needed |
| PC | Windows 10/11, Python 3.11 or newer |

### 1. Start Tessera

Unpack `tessera-host-<version>.zip` from the [latest release](https://github.com/catorendal-a11y/tessera-deck/releases/latest) and double-click `Tessera.cmd`. If Windows warns about a downloaded file, choose *More info* and *Run anyway* (see below). The first start installs Python 3.12 for your user with winget if there is no Python 3.11 or newer, installs the packages from `host/requirements.lock` (each one must match its pinned SHA-256 hash), and puts a shortcut on the Desktop.

**Why Windows warns.** SmartScreen warns about files from the internet that are not signed with a paid
code-signing certificate and that few people have downloaded yet. Tessera is not signed (a signed installer is on
the [roadmap](ROADMAP.md)), so the warning says nothing about the file itself. To check that your download is the
one the release workflow built, compare its SHA-256 with the line for it in `SHA256SUMS` from the same release:

```powershell
Get-FileHash .\tessera-host-v0.7.0.zip -Algorithm SHA256
Get-Content .\SHA256SUMS
```

The two hashes must be the same (`Get-FileHash` prints capitals, `SHA256SUMS` small letters; that does not matter).
With the GitHub CLI you can also check where the zip was built: `gh attestation verify tessera-host-v0.7.0.zip --repo catorendal-a11y/tessera-deck`.

```powershell
Tessera.cmd            # everything: tray icon, USB host and the editor window
```

That is the whole program. The first run creates a Python environment. Closing the editor window leaves the tray
icon and the USB host running; start `Tessera.cmd` again to bring the editor back, or quit from the tray menu.
Enable **Start with Windows** in the tray menu to have it ready after every sign-in.

Optional entry points: `Tessera.cmd --terminal` (terminal UI), `--tray` (tray and host only) and `--editor`
(editor window only). `--setup` installs the dependencies and puts a shortcut on the Desktop, `--uninstall`
removes the autostart entry and the shortcut (add `--purge` to delete your profiles, icons and backups too) and
`--diagnostics` writes a support bundle with versions, counts and a cleaned log tail, and no button contents.
Dependencies are installed again only when `host/requirements.lock` (or, without it, `host/requirements.txt`) changes.

The default port is `COM4`; set `TESSERA_PORT` to change it. After the first successful connection Tessera
remembers the board's USB serial number and follows it if Windows renumbers the port.

### 2. Flash the firmware

**From a release (no developer tools):** the release zip includes the firmware, so choose it in **Panel → Panel firmware …** and press *Install*. Newer firmware comes with *Check for updates*, or put `tessera-firmware-<version>.zip` from the Releases page in the `firmware` folder, choose it there and press *Install*.
On a new board that does not answer yet, the dialog already chooses *Full install (new or blank panel)* under *What to write* and shows *Install anyway*: tick it. The installer verifies the
package, the board and the protocol before writing. The first firmware with A/B update slots must also be
installed once with *Full install*, as it changes the partition table (the installer says so); after that
*Update (keeps settings)* goes over the panel's USB connection and is undone automatically if the new firmware fails
to start. See [`docs/RELEASING.md`](RELEASING.md) for how updates and the rollback work.

**From source:** install [ESP-IDF 6.1](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32p4/get-started/index.html).
Stop the host from the tray first (*Stop host*); it owns the port. Then:

```powershell
idf.py -B build/idf6 build
idf.py -B build/idf6 -p COM4 flash          # first time: bootloader, partition table and app
```

To update only the application — which keeps the bootloader, partition table and stored settings — write the app image:

```powershell
python -m esptool --chip esp32p4 -p COM4 -b 460800 write-flash 0xd000 build\idf6\ota_data_initial.bin 0x10000 build\idf6\tessera.bin
```

The OTA data image makes the bootloader start `ota_0` again, even if an over-USB update left the other slot active.

### 3. Make it yours

Open the editor, open **Apps → Installed programs …** in the action list and drop a program on a key. Changes are saved
automatically after validation to `host/profiles.json`, which is created from `host/profiles.default.json` on the
first start.
