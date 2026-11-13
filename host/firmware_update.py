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
import sys
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

FORMAT = 1
BOARD_ID = 'tessera-p4'
CHIP = 'esp32p4'
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

    @property
    def app(self) -> Image:
        return next(image for image in self.images if image.offset == APP_OFFSET)

    @property
    def otadata(self) -> Image | None:
        return next((image for image in self.images if image.name == OTADATA_NAME), None)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_package(build_dir: Path, out_dir: Path, version: str, protocol: int) -> Path:
    """Zip the images listed in the ESP-IDF build's flasher_args.json together with a manifest."""
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
    manifest = {'format': FORMAT, 'board': BOARD_ID, 'chip': CHIP, 'version': version, 'protocol': protocol,
                'flash': {key: args['flash_settings'][key] for key in ('flash_mode', 'flash_size', 'flash_freq')},
                'files': files, 'needs_full': OTADATA_NAME in blobs}
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f'tessera-firmware-{version}.zip'
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
        if manifest.get('board') != BOARD_ID or manifest.get('chip') != CHIP:
            raise PackageError(f'The package is for {manifest.get("board")!r}, not for a Tessera panel')
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
    if not any(image.offset == APP_OFFSET for image in images):
        raise PackageError('The package has no application image')
    if len({image.offset for image in images}) != len(images):
        raise PackageError('Two images share one flash address')
    return Package(path, version, protocol, flash, tuple(sorted(images, key=lambda image: image.offset)),
                   manifest.get('needs_full') is True)


def command_line(package: Package, port: str, folder: Path, mode: str = 'app', baud: int = 460800) -> list[str]:
    """The esptool command for `mode`: 'app' (application only, keeps settings) or 'full' (all images).

    'app' also resets the OTA data, or the bootloader would keep starting a slot left by an over-USB update.
    """
    if mode not in ('app', 'full'):
        raise ValueError("mode must be 'app' or 'full'")
    chosen = [image for image in (package.otadata, package.app) if image] if mode == 'app' else list(package.images)
    arguments = [sys.executable, '-m', 'esptool', '--chip', CHIP, '-p', port, '-b', str(baud),
                 '--before', 'default-reset', '--after', 'hard-reset', 'write-flash',
                 '--flash-mode', package.flash['flash_mode'], '--flash-size', package.flash['flash_size'],
                 '--flash-freq', package.flash['flash_freq']]
    for image in chosen:
        arguments += [hex(image.offset), str(folder / image.name)]
    return arguments


def run_esptool(arguments: list[str], progress: Callable[[float], None]) -> tuple[int, str]:
    """Run esptool, forwarding its percentage output; returns (exit code, tail of the output)."""
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding='utf-8', errors='replace', bufsize=1,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    tail = ''
    assert process.stdout is not None
    watchdog = threading.Timer(ESPTOOL_TIMEOUT, process.kill)
    watchdog.daemon = True
    watchdog.start()
    try:
        for chunk in iter(process.stdout.readline, ''):
            tail = (tail + chunk)[-OUTPUT_TAIL:]
            found = PROGRESS.findall(chunk)
            if found:
                progress(min(100.0, float(found[-1])))
        code = process.wait()
    finally:  # also when reading fails: a timer left running would kill a later process
        watchdog.cancel()
    return code, tail.strip()


def serial_ota(port: str, data: bytes, progress: Callable[[float], None]) -> None:
    """Send the application over the panel's own USB connection (the host is stopped, so the port is free)."""
    from panel_serial import PanelSerial
    panel = PanelSerial(port, lambda *_: None)
    try:
        panel.ota_upload(data, progress)
    finally:
        panel.close()


def install(package: Package, port: str, identify: Callable[[str], dict | None], mode: str = 'app',
            force: bool = False, progress: Callable[[str, float], None] = lambda stage, percent: None,
            runner: Callable | None = None, ota: Callable | None = None) -> dict:
    """Verify the target and flash it. Never touches a port that identifies as a different board.

    `identify(port)` returns the panel's get_info answer, None when it stays silent (blank or broken
    firmware: allowed only with force=True after the chip check done by esptool) and raises
    PackageError for a device that is clearly not a Tessera panel. In 'app' mode a panel that reports
    "ota":1 is updated over its USB connection with `ota` (serial_ota by default) instead of esptool.
    """
    progress('checking', 0)
    info = identify(port)
    if info is None and not force:
        raise InstallError(f'{port} did not answer as a Tessera panel. If the panel is blank or its firmware is '
                           'broken, choose "Install anyway"; the chip type is still verified before writing.')
    previous = (info or {}).get('firmwareVersion')
    has_slots = (info or {}).get('ota') == 1
    if mode == 'app' and package.needs_full and not has_slots:
        raise InstallError("This firmware changes how the panel's flash is divided (A/B slots for updates over USB). "
                           'Install it once with "Everything"; later updates can use "Application only" again.')
    if mode == 'app' and has_slots and not package.needs_full:
        # An older single-slot firmware would never confirm itself, so the bootloader would roll it back.
        raise InstallError('This firmware is older than the A/B flash layout the panel has now. '
                           'Install it with "Everything".')
    if mode == 'app' and has_slots:
        progress('writing', 0)
        try:
            (ota or serial_ota)(port, package.app.data, lambda percent: progress('writing', percent))
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
                                  'bytes': len(package.app.data), 'needs_full': package.needs_full, 'error': None})
                except PackageError as exc:
                    found.append({'path': str(path), 'version': None, 'protocol': None, 'bytes': 0, 'error': str(exc)})
    return sorted(found, key=lambda item: ([int(n) for n in re.findall(r'\d+', item['version'] or '')], item['path']),
                  reverse=True)
