# Releasing and updating

[Back to the README](../README.md)

## Versions

`VERSION` holds one number (for example `0.7.0`). The firmware (`PROJECT_VER`), the host, the firmware packages and the release tag all use it.

The firmware's USB protocol has its own number in `main/protocol_version.h`. The host accepts the protocols listed in `SUPPORTED_PROTOCOLS` in `host/panel_serial.py`. It refuses a panel outside that range with a message that says which side to update.

| Protocol | Added |
|---|---|
| 1 | Original firmware |
| 2 | `protocol` field in `get_info`, long-press (`hold`) events |
| 3 | Per-key colors, the ambient screen (`AD_SCREEN ambient`, `AD_AMBIENT`), the offline layout |
| 4 | The cockpit: a rail of four screens (keys, agents, mixer, status) with `AD_AGENTS`, `AD_MIXER`, `AD_STATS`, `AD_VIEW`, `AD_RAIL`, wide keys, touch lines back |

The A/B update fields (`"ota":1`, `AD_OTA_*`) came with firmware 0.7.0 and did not change the protocol number. Older hosts ignore the new handshake fields.

The configuration file has its own `version` (currently 2). Opening an older file migrates it. A file from a newer Tessera is refused with a clear message instead of being damaged.

## Make a release

1. Rename `## Unreleased` in `CHANGELOG.md` to `## <version>`, for example `## 0.7.1`. Put a fresh `## Unreleased` above it if you want one.
2. Set `VERSION` to the same number.
3. Run the checks from [CONTRIBUTING.md](../CONTRIBUTING.md) and the native UI test.
4. Commit and push, then tag and push the tag:

   ```powershell
   git tag v0.7.1
   git push origin v0.7.1
   ```

5. The *Release* workflow (`.github/workflows/release.yml`) starts on the tag and publishes the release.

### What the workflow does

| Job | Steps |
|---|---|
| `release` (ESP-IDF 6.1 container) | Checks that the tag equals `v` plus `VERSION`. Checks that `CHANGELOG.md` has a `## <version>` heading. Builds the firmware with `idf.py -B build/idf6 build`. Runs the native LVGL tests. Packages the firmware with `tools/package_firmware.py`. Makes `tessera-host-<tag>.zip` from `git archive` with the firmware package inside. Writes `SHA256SUMS`. |
| `host-tests` (Windows) | Installs `host/requirements.lock` with `--require-hashes` and runs the host tests. |
| `publish` | Starts only when both jobs above pass. Takes the release notes from the `CHANGELOG.md` section, word for word, and stops if the section is empty. Signs a build attestation for the zips. Creates the GitHub release with `tessera-firmware-<version>.zip`, `tessera-host-<tag>.zip` and `SHA256SUMS`. |

The workflow stops early when the tag does not match `VERSION` or the changelog heading is missing, so a wrong tag does not publish anything.

Anyone can check that a download came from this workflow:

```powershell
gh attestation verify tessera-host-v0.7.0.zip --repo catorendal-a11y/tessera-deck
```

[INSTALL.md](INSTALL.md) also explains how to compare a download with `SHA256SUMS`.

### Firmware packages

A firmware package is a zip with `manifest.json` and the images. The manifest holds the board, chip, version, protocol, flash settings and the SHA-256 of every image. Build one locally with:

```powershell
python tools/package_firmware.py build/idf6 dist
```

## Update the panel

Use **Panel → Panel firmware and updates …** in the editor, or `esptool` by hand (see [INSTALL.md](INSTALL.md)). The installer checks the package (format, board, chip, protocol, checksums), asks the panel who it is, stops the host, writes the firmware and starts the host again.

| Choice | When it is the default | What it writes |
|---|---|---|
| Update (keeps settings) | A panel is connected | The app only, so the stored brightness and offline layout survive |
| Full install (new or blank panel) | No panel is connected | The app, bootloader, partition table and OTA data, with esptool |

## A/B slots and rollback

`partitions.csv` defines two 6 MB application slots (`ota_0` at 0x10000 and `ota_1`), `otadata`, a 16 KB `nvs` and a `storage` SPIFFS partition for the offline layout.

A panel that reports `"ota":1` takes *Update* over its own USB connection (`AD_OTA_*`, see [PROTOCOL.md](PROTOCOL.md)) into the idle slot:

1. The panel checks the SHA-256 and restarts into the new slot.
2. It confirms the new firmware after its first handshake with the host, or after 60 s.
3. If the new firmware crashes or hangs before that, the bootloader goes back to the previous slot on the next reset.

If the panel does not answer, esptool through the ROM bootloader still works. Unplug the panel, plug it in and install again. An esptool *Update* writes the app to `ota_0` and resets `otadata` so that slot boots.

Rollback is written and tested in simulation. It has not been tried on the panel; see [VERIFICATION.md](../VERIFICATION.md).

### The first A/B install needs a full install

Packages built for the A/B table contain `ota_data_initial.bin` and carry `"needs_full": true` in `manifest.json`. `tools/package_firmware.py` refuses a build without the OTA data.

- The installer refuses *Update* for such a package while the panel does not report `"ota":1` (older single-slot firmware).
- It also refuses an older package on an A/B panel.
- The full install keeps NVS (the brightness) unless its pages no longer fit the smaller partition. The old offline layout is not carried over, and the host pushes it again.

## Check for a new version

*Check for updates* in the firmware dialog asks GitHub for the latest release when you press it. It can download the firmware package, which is kept only if its SHA-256 matches the release's `SHA256SUMS`.

The Windows program updates by replacing the folder with the new `tessera-host` zip, or by `git pull`. To keep your setup when you replace the folder, copy these from the old `host/` folder: `profiles.json`, `assets/`, `backups/`, `state.local.json` (counters and timers), `icon-library.local.json`, `editor.local.json`, `deck-device.local.json` and `profiles-previous.local.json`. This is the same list `--purge` deletes (`USER_DATA` in `host/setup_tool.py`).
