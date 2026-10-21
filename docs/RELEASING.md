# Releasing and updating

## Versions

`VERSION` holds one number (for example `0.5.0`) used by the firmware (`PROJECT_VER`), the host, the firmware
packages and the release tag. The firmware's USB protocol has its own number in `main/protocol_version.h`; the host
accepts the protocols listed in `SUPPORTED_PROTOCOLS` in `host/tesserad.py` and refuses a panel outside that range
with a message that says which side to update.

| Protocol | Added |
|---|---|
| 1 | Original firmware |
| 2 | `protocol` field in `get_info`, long-press (`hold`) events |
| 3 | Per-key colors, the ambient screen (`AD_SCREEN ambient`, `AD_AMBIENT`), the offline layout |

The configuration file has its own `version` (currently 2). Opening an older file migrates it; a file from a newer
Tessera is refused with a clear message instead of being damaged.

## Making a release

1. Update `VERSION` and `CHANGELOG.md`; run the tests (`python -m unittest discover -s tests`) and the native render
   test.
2. Commit, then tag: `git tag v0.5.0 && git push origin v0.5.0`.
3. The *Release* workflow builds the firmware in the ESP-IDF 6.1 container, runs `tools/package_firmware.py`, zips
   the host sources and publishes `tessera-firmware-<version>.zip`, `tessera-host-<tag>.zip` and `SHA256SUMS`. It
   refuses a tag that does not match `VERSION`.

A firmware package is a zip with `manifest.json` (board, chip, version, protocol, flash settings and the SHA-256
of every image) and the images. Build one locally with `python tools/package_firmware.py build/idf6 dist`.

## Updating the panel

Use **⋯ → Panel firmware …** in the editor (or `esptool` by hand, see the README). The installer checks the package
(format, board, chip, protocol, checksums), asks the panel who it is, stops the host, writes with esptool and
starts the host again. *Application only* (the default) writes only the app image, so the stored brightness and
the offline layout survive; *Everything* also writes the bootloader and partition table.

**Why there is no automatic rollback.** The partition table has a single application partition (`factory`, 8 MB),
not two OTA slots, so a bad image cannot fall back to the previous one on its own. What protects the user is that
the chip's ROM bootloader always accepts a new image over USB, so a failed update can be retried (unplug, plug in,
install again). Moving to an A/B layout with over-USB OTA would add real rollback, but it needs a new partition
table (a one-time full flash that also clears stored settings), new firmware code to receive and verify an image,
and testing on hardware, so it is deliberately not part of 0.5.0.

## Checking for a new version

*Check for updates* in the firmware dialog asks GitHub for the latest release when you press it and can download
the firmware package, which is kept only if its SHA-256 matches the release's `SHA256SUMS`. The Windows program
itself is updated by replacing the folder with the new `tessera-host` zip (your profiles, icons and backups live
in `host/` and are kept if you copy them over) or by `git pull`.
