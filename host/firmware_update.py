"""Firmware packages and USB installation for the Tessera panel.

A package is a zip with the ESP-IDF images and a manifest that names the board, the chip, the
version, the host protocol and the SHA-256 of every image. Installing verifies all of that before a
single byte is written, writes only what is needed (the application image by default, so settings
stored on the panel survive) and reports progress.

A panel that reports "ota":1 in its handshake receives the application over its own USB line protocol
into the idle A/B slot; it verifies the image, boots it and goes back to the previous slot if the new
firmware never confirms itself. Everything else uses esptool through the chip's ROM bootloader, which
stays available however the flash ends up, so a failed update can always be retried.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
import subprocess
from process_flags import NO_WINDOW
import time
import sys
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

FORMAT = 1
BOARD_ID = 'tessera-p4'  # the default board of build_package
CHIP = 'esp32p4'
BOARD_CHIPS = {'tessera-p4': 'esp32p4', 'tessera-p4-v3': 'esp32p4', 'tessera-p4-crowpanel7': 'esp32p4', 'tessera-s3-ws7': 'esp32s3', 'tessera-s3-8048s070': 'esp32s3', 'tessera-s3-crowpanel7': 'esp32s3'}
V3_BOARDS = frozenset({'tessera-p4-v3'})  # ESP32-P4 builds for chip revision v3.x; the other P4 builds are for v1.x
P4_UART_BOARDS = frozenset({'tessera-p4-crowpanel7'})  # P4 boards whose host link is a USB-UART bridge (CH340)
BOARD_NAMES = {'tessera-p4': 'GUITION JC1060P470C', 'tessera-p4-v3': 'GUITION JC1060P470C (v3.x chip)',
               'tessera-p4-crowpanel7': 'Elecrow CrowPanel Advance 7.0 (ESP32-P4)',
               'tessera-s3-ws7': 'Waveshare ESP32-S3-Touch-LCD-7', 'tessera-s3-8048s070': 'Sunton ESP32-8048S070',
               'tessera-s3-crowpanel7': 'Elecrow CrowPanel Advance 7.0 (ESP32-S3)'}
# "Chip is" before esptool 5; "Unknown ESP32-P4" for a package version esptool has no name for
CHIP_LINE = re.compile(r'Chip (?:type:|is)\s+(?:Unknown )?(ESP32-[A-Z]\d+).*?\(revision v(\d+)\.(\d+)\)')
MANIFEST = 'manifest.json'
APP_OFFSET = 0x10000
OTADATA_NAME = 'ota_data_initial.bin'  # written with the app by esptool so the bootloader starts ota_0 again
MAX_IMAGE_BYTES = 8 * 1024 * 1024
PROGRESS = re.compile(r'(\d+(?:\.\d+)?)\s*%')
OUTPUT_TAIL = 400
ESPTOOL_TIMEOUT = 300  # seconds; a full write takes about one minute


class PackageError(ValueError):
    """The package is damaged, for another board or not supported by this host."""


class InstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class Image:
    offset: int
    name: str
    data: bytes


@dataclass(frozen=True)
class Package:
    path: Path
    version: str
    protocol: int
    flash: dict
    images: tuple[Image, ...]
    needs_full: bool = False  # A/B layout: a panel without it ("ota" missing) must get the full install once
    board: str = BOARD_ID
    chip: str = CHIP

    @property
    def app(self) -> Image:
        return next(image for image in self.images if image.offset == APP_OFFSET)

    @property
    def otadata(self) -> Image | None:
        return next((image for image in self.images if image.name == OTADATA_NAME), None)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package_name(board: str, version: str) -> str:
    """tessera-firmware-<version>.zip for the P4 (as always), tessera-firmware-<board>-<version>.zip for the others."""
    return f'tessera-firmware-{version}.zip' if board == BOARD_ID else f'tessera-firmware-{board}-{version}.zip'


def app_slot_size(table: bytes) -> int | None:
    """Size of the application slot (factory or ota_0) in a binary ESP-IDF partition table; None if unreadable."""
    for start in range(0, len(table) - 31, 32):
        entry = table[start:start + 32]
        if entry[:2] != b'\xaa\x50':
            break
        if entry[2] == 0 and entry[3] in (0, 0x10):  # type app, subtype factory or ota_0
            return int.from_bytes(entry[8:12], 'little')
    return None


def build_package(build_dir: Path, out_dir: Path, version: str, protocol: int,
                  board: str = BOARD_ID, chip: str = CHIP) -> Path:
    """Zip the images listed in the ESP-IDF build's flasher_args.json together with a manifest."""
    if BOARD_CHIPS.get(board) != chip:
        raise PackageError(f'{board!r} is not a known board for chip {chip!r}')
    build_dir, out_dir = Path(build_dir), Path(out_dir)
    args = json.loads((build_dir / 'flasher_args.json').read_text(encoding='utf-8'))
    files = []
    blobs = {}
    for offset, relative in sorted(args['flash_files'].items(), key=lambda item: int(item[0], 16)):
        data = (build_dir / relative).read_bytes()
        name = Path(relative).name
        blobs[name] = data
        files.append({'offset': offset, 'file': name, 'sha256': sha256(data)})
    # Every image the build flashes goes in, ota_data_initial.bin included. Its presence marks the A/B partition
    # table, which a panel still on the old single-slot table only gets from a full install.
    manifest = {'format': FORMAT, 'board': board, 'chip': chip, 'version': version, 'protocol': protocol,
                'flash': {key: args['flash_settings'][key] for key in ('flash_mode', 'flash_size', 'flash_freq')},
                'files': files, 'needs_full': OTADATA_NAME in blobs}
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / package_name(board, version)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST, json.dumps(manifest, indent=2) + '\n')
        for name, data in blobs.items():
            archive.writestr(name, data)
    (out_dir / (target.name + '.sha256')).write_text(f'{sha256(target.read_bytes())}  {target.name}\n')
    return target


def load_package(path: Path, supported_protocols: tuple[int, ...]) -> Package:
    """Read and fully verify a package; raises PackageError with a plain explanation."""
    path = Path(path)
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackageError(f'{path.name} is not a firmware package: {exc}') from exc
    with archive:
        try:
            manifest = json.loads(archive.read(MANIFEST))
        except Exception as exc:  # zipfile raises BadZipFile, zlib.error, NotImplementedError and more
            raise PackageError('The package has no readable manifest.json') from exc
        if not isinstance(manifest, dict) or manifest.get('format') != FORMAT:
            raise PackageError('The package format is not supported by this version of Tessera')
        board, chip = manifest.get('board'), manifest.get('chip')
        if not isinstance(board, str) or BOARD_CHIPS.get(board) != chip:
            raise PackageError(f'The package is for {board!r}, not for a Tessera panel')
        protocol = manifest.get('protocol')
        if type(protocol) is not int or protocol not in supported_protocols:
            raise PackageError(f'The firmware speaks protocol {protocol!r}, this host supports '
                               f'{supported_protocols[0]}-{supported_protocols[-1]}. Update Tessera first.')
        version = manifest.get('version')
        flash = manifest.get('flash')
        if (not isinstance(version, str) or not version or not isinstance(flash, dict)
                or any(not isinstance(flash.get(key), str) for key in ('flash_mode', 'flash_size', 'flash_freq'))
                or not isinstance(manifest.get('files', []), list)):
            raise PackageError('The manifest is incomplete')
        images = []
        for entry in manifest.get('files', []):
            try:
                offset, name, expected = int(entry['offset'], 16), entry['file'], entry['sha256']
            except (KeyError, TypeError, ValueError) as exc:
                raise PackageError('The manifest lists an unreadable file') from exc
            if not isinstance(name, str) or Path(name).name != name or name == MANIFEST:
                raise PackageError(f'Unsafe file name in the package: {name!r}')
            try:
                info = archive.getinfo(name)
            except KeyError as exc:
                raise PackageError(f'{name} is listed but missing from the package') from exc
            if info.file_size > MAX_IMAGE_BYTES:
                raise PackageError(f'{name} is larger than {MAX_IMAGE_BYTES // 1024 // 1024} MiB')
            try:
                data = archive.read(name)
            except Exception as exc:  # a damaged member: one bad package must not break the whole list
                raise PackageError(f'{name} is damaged: {exc}') from exc
            if sha256(data) != expected:
                raise PackageError(f'{name} is damaged (checksum mismatch)')
            images.append(Image(offset, name, data))
    app = next((image for image in images if image.offset == APP_OFFSET), None)
    if app is None:
        raise PackageError('The package has no application image')
    table = next((image.data for image in images if image.name == 'partition-table.bin'), b'')
    slot = app_slot_size(table)
    if slot is not None and len(app.data) > slot:
        raise PackageError(f'The application ({len(app.data)} bytes) does not fit its {slot // 1024} KiB flash slot')
    if len({image.offset for image in images}) != len(images):
        raise PackageError('Two images share one flash address')
    return Package(path, version, protocol, flash, tuple(sorted(images, key=lambda image: image.offset)),
                   manifest.get('needs_full') is True, board, chip)


def command_line(package: Package, port: str, folder: Path, mode: str = 'app', baud: int = 460800) -> list[str]:
    """The esptool command for `mode`: 'app' (application only, keeps settings) or 'full' (all images).

    'app' also resets the OTA data, or the bootloader would keep starting a slot left by an over-USB update.
    """
    if mode not in ('app', 'full'):
        raise ValueError("mode must be 'app' or 'full'")
    chosen = [image for image in (package.otadata, package.app) if image] if mode == 'app' else list(package.images)
    arguments = [sys.executable, '-m', 'esptool', '--chip', package.chip, '-p', port, '-b', str(baud),
                 '--before', 'default-reset', '--after', 'hard-reset', 'write-flash',
                 '--flash-mode', package.flash['flash_mode'], '--flash-size', package.flash['flash_size'],
                 '--flash-freq', package.flash['flash_freq']]
    for image in chosen:
        arguments += [hex(image.offset), str(folder / image.name)]
    return arguments


def run_esptool(arguments: list[str], progress: Callable[[float], None], keep: int = OUTPUT_TAIL) -> tuple[int, str]:
    """Run esptool, forwarding its percentage output; returns (exit code, the last `keep` characters of the output)."""
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding='utf-8', errors='replace', bufsize=1,
                               creationflags=NO_WINDOW)
    tail = ''
    assert process.stdout is not None
    watchdog = threading.Timer(ESPTOOL_TIMEOUT, process.kill)
    watchdog.daemon = True
    watchdog.start()
    try:
        for chunk in iter(process.stdout.readline, ''):
            tail = (tail + chunk)[-keep:]
            found = PROGRESS.findall(chunk)
            if found:
                progress(min(100.0, float(found[-1])))
        code = process.wait()
    finally:  # also when reading fails: a timer left running would kill a later process
        watchdog.cancel()
    return code, tail.strip()


def boards_for(chip: str, major: int) -> list[str]:
    """The boards a chip can be. The two P4 revisions take different builds, so the revision narrows it down."""
    return [board for board, its in BOARD_CHIPS.items()
            if its == chip and (chip != 'esp32p4' or (board in V3_BOARDS) == (major >= 3))]


def detect_chip(port: str, runner: Callable | None = None, uart: bool = False) -> dict:
    """Ask the ROM bootloader on `port` which chip it is: the way to tell boards apart when no firmware answers.

    Reads only (esptool read-mac) and restarts the chip afterwards. Returns the chip, its revision and the boards
    it can be; raises InstallError when nothing answers or the chip is not one Tessera has firmware for.
    `uart` is True when `port` is a USB-UART bridge (CH340) rather than the chip's own USB.
    """
    code, output = (runner or run_esptool)([sys.executable, '-m', 'esptool', '-p', port, '--before', 'default-reset',
                                            '--after', 'hard-reset', 'read-mac'], lambda percent: None, 4000)
    found = CHIP_LINE.search(output)
    if code or not found:
        raise InstallError(f'{port} has no ESP32 that answers. Check the cable (it must carry data), or hold the '
                           f"board's BOOT button while you plug it in, and look again. {output[-OUTPUT_TAIL:].strip()}")
    name, major, minor = found.group(1), int(found.group(2)), found.group(3)
    chip = name.lower().replace('-', '')
    boards = boards_for(chip, major)
    if chip == 'esp32p4' and uart:
        # The GUITION P4 has only the chip's own USB; a P4 behind a UART bridge is the CrowPanel, which has no
        # build for the v3.x chip yet. Offering the GUITION v3 package there would write the wrong pins.
        boards = [board for board in boards if board in P4_UART_BOARDS]
        if not boards:
            raise InstallError(f'{port} has an {name} revision v{major}.{minor} behind a USB-UART bridge, as on the Elecrow '
                               'CrowPanel Advance 7.0. Tessera has no firmware yet for that board with a v3.x chip, so '
                               'nothing was written. Leave the firmware it came with on the board for now.')
    if not boards:
        raise InstallError(f'{port} has an {name}, and there is no Tessera firmware for that chip.')
    return {'chip': chip, 'revision': f'{major}.{minor}', 'boards': boards}


NEW_FIRMWARE_SECONDS = 30  # the new image checks itself and boots in a few seconds
KEPT_SECONDS = 70  # a new image keeps itself once it has run for a minute (app_confirm in main/main.cpp)
LOOK_AGAIN = ('Once the host has found the panel again, Panel firmware and updates shows which firmware it runs. '
              'If it is still the old one, install again.')


def await_new_firmware(panel, boot, version: str | None) -> None:
    """Wait on the open port until the restarted panel answers get_info, which makes it keep the new image.

    On Linux opening the port resets the panel. The new image is on probation until it has answered once, and a
    reset before that boots the old one again, so the host must not open the port before this returns.
    """
    from panel_serial import DeviceRejected
    deadline = time.monotonic() + NEW_FIRMWARE_SECONDS
    info = None
    while info is None and time.monotonic() < deadline:
        try:
            panel.verify()
        except DeviceRejected as exc:
            if exc.kind != 'silent':
                raise
            continue  # still booting
        except OSError:
            # The chip's own USB (USB Serial/JTAG, as on the GUITION board) goes away while it restarts, and the open
            # port with it. Close it at once, or Linux gives the returning device another name. Opening the port
            # again resets the panel, so that waits until the new image has run long enough to keep itself.
            panel.close()
            time.sleep(KEPT_SECONDS)
            info = reopen(panel.ser.port)
            break
        if panel.info.get('bootId') != boot:  # otherwise the answer of the old firmware before it restarted
            info = panel.info
    if info is None:
        raise InstallError(f'The panel took the new firmware and restarted, but it did not answer. {LOOK_AGAIN}')
    if version and info.get('firmwareVersion') != version:
        raise InstallError(f'The panel took firmware {version}, but started {info.get("firmwareVersion")} again after '
                           'the restart, so the new firmware did not stay. Install it once more. If it goes back again, '
                           'choose "Full install".')


def reopen(port: str) -> dict | None:
    """get_info of the panel on `port` once it is back on USB after a restart; None when it stays silent."""
    from panel_serial import DeviceRejected, PanelSerial
    deadline = time.monotonic() + NEW_FIRMWARE_SECONDS
    while True:
        try:
            with contextlib.closing(PanelSerial(port, lambda *_: None)) as panel:
                return panel.info
        except DeviceRejected as exc:
            if exc.kind != 'silent':
                raise
            return None
        except OSError as exc:  # not back on USB yet
            if time.monotonic() >= deadline:
                raise InstallError(f'The panel took the new firmware and restarted, but {port} did not come back. '
                                   f'Check the USB cable. {LOOK_AGAIN}') from exc
        time.sleep(1)


def serial_ota(port: str, data: bytes, progress: Callable[[float], None], version: str | None = None) -> None:
    """Send the application over the panel's own USB connection (the host is stopped, so the port is free)."""
    from panel_serial import PanelSerial
    boot, sent_all = None, False
    for attempt in (1, 2):
        panel = PanelSerial(port, lambda *_: None)
        try:
            # The answer to AD_OTA_END can get lost like any other (see ota_upload). A panel that has restarted since
            # and runs the version that was sent took the image: sending it again would only install it twice.
            if sent_all and panel.info.get('bootId') != boot and version and panel.info.get('firmwareVersion') == version:
                progress(100)
                return
            boot = panel.info.get('bootId')
            panel.ota_upload(data, progress)
            if panel.resets_on_open():
                await_new_firmware(panel, boot, version)
            return
        except TimeoutError as exc:
            # The panel keeps its running firmware until it has checked a whole image, so one fresh start is safe.
            if attempt == 2:
                raise
            sent_all = 'AD_OTA_END' in str(exc)
            try:
                panel.send_line('AD_OTA_ABORT')
            except OSError:
                pass
        finally:
            panel.close()
        time.sleep(2)


def install(package: Package, port: str, identify: Callable[[str], dict | None], mode: str = 'app',
            force: bool = False, progress: Callable[[str, float], None] = lambda stage, percent: None,
            runner: Callable | None = None, ota: Callable | None = None) -> dict:
    """Verify the target and flash it. Never touches a port that identifies as a different board.

    `identify(port)` returns the panel's get_info answer, None when it stays silent (blank or broken
    firmware: allowed only with force=True after the chip check done by esptool) and raises
    PackageError for a device that is clearly not a Tessera panel. In 'app' mode a panel that reports
    "ota":1 is updated over its USB connection with `ota` (serial_ota by default) instead of esptool.
    A Tessera panel whose protocol this host does not speak comes back as {"protocolUnknown": True}
    and can only get the full install.
    """
    progress('checking', 0)
    info = identify(port)
    if info is None and not force:
        raise InstallError(f'{port} did not answer as a Tessera panel. If it is new, blank or its firmware is broken, '
                           'choose "Full install" and install again. '
                           'The chip type is still verified before writing.')
    if info and info.get('boardId') not in (None, package.board):
        raise InstallError(f'This package is for {package.board}, but the connected panel is {info["boardId"]}. '
                           'Choose the package that matches the panel.')
    previous = (info or {}).get('firmwareVersion')
    has_slots = (info or {}).get('ota') == 1
    if mode == 'app' and (info or {}).get('protocolUnknown'):
        raise InstallError('The panel runs firmware this version of Tessera cannot talk to, such as the Wi-Fi beta '
                           'or a newer release. To install this one, choose "Full install".')
    if mode == 'app' and package.needs_full and not has_slots:
        raise InstallError("This firmware changes how the panel's flash is divided (A/B slots for updates over USB). "
                           'Install it once with "Full install"; later updates can use "Update" again.')
    if mode == 'app' and has_slots and not package.needs_full:
        # An older single-slot firmware would never confirm itself, so the bootloader would roll it back.
        raise InstallError('This firmware is older than the A/B flash layout the panel has now. '
                           'Install it with "Full install".')
    if mode == 'app' and has_slots:
        progress('writing', 0)
        try:
            send = ota or (lambda *arguments: serial_ota(*arguments, version=package.version))
            send(port, package.app.data, lambda percent: progress('writing', percent))
        except (OSError, ValueError) as exc:  # TimeoutError is an OSError
            raise InstallError(f'The update over USB failed ({exc}). The panel keeps its current firmware; '
                               'unplug and plug in the cable and try again.') from exc
        progress('done', 100)
        return {'previous': previous, 'installed': package.version, 'mode': mode}
    with tempfile.TemporaryDirectory(prefix='tessera-firmware-') as folder:
        for image in package.images:
            (Path(folder) / image.name).write_bytes(image.data)
        progress('writing', 0)
        code, tail = (runner or run_esptool)(command_line(package, port, Path(folder), mode),
                            lambda percent: progress('writing', percent))
    if code and 'requires chip revision' in tail:
        raise InstallError('This package does not fit the chip revision of the panel, and nothing was written. '
                           'GUITION boards with an ESP32-P4 v3.x chip take the tessera-p4-v3 package; older ones take '
                           f'tessera-firmware-<version>.zip. {tail}')
    if code:
        raise InstallError('Flashing failed and the panel may be in download mode. Unplug the cable, plug it in '
                           f'again and retry; the ROM bootloader always allows another attempt. {tail}')
    progress('done', 100)
    return {'previous': previous, 'installed': package.version, 'mode': mode}


def find_packages(folders: list[Path], supported_protocols: tuple[int, ...]) -> list[dict]:
    """Verified packages found in `folders`, newest first; damaged ones are listed with their error."""
    found = []
    for folder in folders:
        for path in sorted(Path(folder).glob('tessera-firmware-*.zip')):
            with contextlib.suppress(OSError):
                try:
                    package = load_package(path, supported_protocols)
                    found.append({'path': str(path), 'version': package.version, 'protocol': package.protocol,
                                  'bytes': len(package.app.data), 'needs_full': package.needs_full, 'board': package.board, 'error': None})
                except PackageError as exc:
                    found.append({'path': str(path), 'version': None, 'protocol': None, 'bytes': 0, 'board': None, 'error': str(exc)})
    return sorted(found, key=lambda item: ([int(n) for n in re.findall(r'\d+', item['version'] or '')], item['path']),
                  reverse=True)
