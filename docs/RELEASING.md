# Releasing and updating

## Versions

`VERSION` holds one number (for example `0.6.0`) used by the firmware (`PROJECT_VER`), the host, the firmware
packages and the release tag. The firmware's USB protocol has its own number in `main/protocol_version.h`; the host
accepts the protocols listed in `SUPPORTED_PROTOCOLS` in `host/panel_serial.py` and refuses a panel outside that range
with a message that says which side to update.

| Protocol | Added |
|---|---|
| 1 | Original firmware |
| 2 | `protocol` field in `get_info`, long-press (`hold`) events |
| 3 | Per-key colors, the ambient screen (`AD_SCREEN ambient`, `AD_AMBIENT`), the offline layout |
| 4 | The cockpit: a rail of four screens (keys, agents, mixer, status) with `AD_AGENTS`, `AD_MIXER`, `AD_STATS`, `AD_VIEW`, `AD_RAIL`, wide keys and touch lines back |

The configuration file has its own `version` (currently 2). Opening an older file migrates it; a file from a newer
Tessera is refused with a clear message instead of being damaged.

## Making a release

1. Update `VERSION` and `CHANGELOG.md`; run the tests (`python -m unittest discover -s tests`) and the native render
   test.
2. Commit, then tag: `git tag v0.6.0 && git push origin v0.6.0`.
3. The *Release* workflow builds the firmware in the ESP-IDF 6.1 container, runs `tools/package_firmware.py`, zips
   the host sources with the firmware package inside and publishes `tessera-firmware-<version>.zip`, `tessera-host-<tag>.zip` and `SHA256SUMS`. It
   refuses a tag that does not match `VERSION`.

### Release notes, tests and provenance

- **Notes:** rename `## Unreleased` in `CHANGELOG.md` to `## <version>` (for example `## 0.6.3`) before tagging.
  The workflow stops if that heading is missing, and the release notes are that section, word for word.
- **Tests:** a Windows job installs `host/requirements.lock` with `--require-hashes` and runs the host tests; the
  release is published only when they and the firmware build pass.
- **Provenance:** the zips get a signed build attestation (`actions/attest-build-provenance`), so anyone can check
  that a download was built by this workflow from this repository:
  `gh attestation verify tessera-host-v0.7.0.zip --repo catorendal-a11y/tessera-deck`.

A firmware package is a zip with `manifest.json` (board, chip, version, protocol, flash settings and the SHA-256
of every image) and the images. Build one locally with `python tools/package_firmware.py build/idf6 dist`.

## Updating the panel

Use **Panel → Panel firmware …** in the editor (or `esptool` by hand, see [Install](INSTALL.md)). The installer checks the package
(format, board, chip, protocol, checksums), asks the panel who it is, stops the host, writes the firmware and
starts the host again. *Update (keeps settings)* (the default for a connected panel) writes only the app, so the stored brightness and
the offline layout survive; *Full install (new or blank panel)*, the default when no panel is connected, also writes the bootloader, partition table and OTA data with esptool.

**A/B slots and rollback.** The partition table has two 6 MB application slots (`ota_0` at 0x10000, `ota_1`),
`otadata`, a 16 KB `nvs` and a `storage` SPIFFS partition (the offline layout). A panel that reports `"ota":1`
gets *Update* over its own USB connection (`AD_OTA_*`, see [Protocol](PROTOCOL.md)) into the idle slot:
it checks the SHA-256, restarts into it and confirms it after the first handshake with the host (or 60 s). A new
firmware that crashes or hangs before that is undone by the bootloader on the next reset. When the panel does not
answer, esptool through the ROM bootloader is always available, so a failed update can be retried (unplug, plug
in, install again); an esptool *Update* writes the app to `ota_0` and resets `otadata` so that slot boots.

**The first A/B install needs *Full install*.** Packages built for the A/B table contain `ota_data_initial.bin` and
carry `"needs_full": true` in `manifest.json` (`tools/package_firmware.py` refuses a build without the OTA data).
The installer refuses *Update* for such a package while the panel does not report `"ota":1` (older
single-slot firmware), and refuses it the other way round for an older package on an A/B panel. The protocol stays
4: older hosts ignore the new handshake fields. The full install keeps NVS (the brightness) unless its pages no
longer fit the smaller partition; the old offline layout is not carried over, the host pushes it again.

## Checking for a new version

*Check for updates* in the firmware dialog asks GitHub for the latest release when you press it and can download
the firmware package, which is kept only if its SHA-256 matches the release's `SHA256SUMS`. The Windows program
itself is updated by replacing the folder with the new `tessera-host` zip (your profiles, icons and backups live
in `host/` and are kept if you copy them over) or by `git pull`.
