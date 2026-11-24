"""The update check against the project's GitHub releases, and the verified downloads.

The check runs when the user presses the button, and once a day from the tray if the user chose that
(tessera_tray.auto_update_check). Nothing is downloaded until the user asks for it. Only the project's own release API and GitHub's
download hosts are used, downloads are limited in size, and a firmware package or a program zip is kept only
when its SHA-256 matches the SHA256SUMS file published with the same release.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import zipfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

REPOSITORY = 'catorendal-a11y/tessera-deck'
RELEASE_API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
DOWNLOAD_HOSTS = ('github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com')
TIMEOUT_SECONDS = 10
MAX_DOWNLOAD = 16 * 1024 * 1024
MAX_HOST_DOWNLOAD = 64 * 1024 * 1024  # the program zip holds the firmware of every board
MAX_UNPACKED = 256 * 1024 * 1024
# What the user made, as in setup_tool.USER_DATA. A release never holds these; a zip that does is not written over them.
USER_FILES = re.compile(r'host/(profiles\.json|assets/.*|backups/.*|plugins/[^/]+\.log.*|[^/]*\.local\.[^/]*)')
NOTES_LINES = 10
VERSION = re.compile(r'v?(\d+)\.(\d+)\.(\d+)')
FIRMWARE_ASSET = re.compile(r'tessera-firmware-[0-9A-Za-z.\-]+\.zip')
HOST_ASSET = re.compile(r'tessera-host-v\d+\.\d+\.\d+\.zip')
P4_ASSET = re.compile(r'tessera-firmware-v?\d[0-9A-Za-z.\-]*\.zip')  # the P4 package has no board in its name


def firmware_asset(assets: list, board: str | None) -> dict | None:
    """The release package for `board`; the P4 (and a panel whose board is not known) gets the one without a board."""
    if board and board != 'tessera-p4':
        wanted = re.compile(rf'tessera-firmware-{re.escape(board)}-v?\d[0-9A-Za-z.\-]*\.zip')
        return next((item for item in assets if wanted.fullmatch(item['name'])), None)
    return next((item for item in assets if P4_ASSET.fullmatch(item['name'])), None)


def parse_version(text: str) -> tuple[int, int, int]:
    match = VERSION.fullmatch(str(text).strip())
    if not match:
        raise ValueError(f'Not a version number: {text!r}')
    return tuple(int(part) for part in match.groups())


def _open(url: str, opener, limit: int) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={'User-Agent': 'Tessera-Deck', 'Accept': '*/*'})
    with opener(request, timeout=TIMEOUT_SECONDS) as reply:
        final = reply.geturl() if hasattr(reply, 'geturl') else url
        data = reply.read(limit + 1)
    if len(data) > limit:
        raise ValueError('The download is larger than expected')
    return data, final


def _check_host(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ''
    allowed = host in DOWNLOAD_HOSTS or host.endswith('.githubusercontent.com')
    if parsed.scheme != 'https' or not allowed:
        raise ValueError('Updates are only downloaded from GitHub over https')


class _GitHubRedirects(urllib.request.HTTPRedirectHandler):
    """Every redirect hop must stay on GitHub over https, checked before anything is fetched from it."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _urlopen(request, timeout):
    return urllib.request.build_opener(_GitHubRedirects).open(request, timeout=timeout)


def notes_excerpt(body, lines: int = NOTES_LINES) -> str:
    """The first non-empty lines of the release notes, short enough for a notice or a dialog."""
    if not isinstance(body, str):
        return ''
    kept = [line.rstrip()[:200] for line in body.splitlines() if line.strip()][:lines]
    return '\n'.join(kept)


def check(current: str, opener=_urlopen, board: str | None = None) -> dict:
    """Compare `current` with the latest published release; `board` picks the firmware package of the connected panel."""
    try:
        raw, _ = _open(RELEASE_API, opener, 512 * 1024)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError('No firmware has been published on GitHub yet.') from exc
        if exc.code in (403, 429):
            raise ValueError('GitHub is limiting requests from this address. Try again in an hour.') from exc
        raise ValueError(f'GitHub answered with an error (HTTP {exc.code}). Try again later.') from exc
    except OSError as exc:  # URLError: no network, no DNS, a time-out
        raise ValueError('GitHub could not be reached. Check the internet connection and try again.') from exc
    try:
        release = json.loads(raw)
        latest = release['tag_name']
        newer = parse_version(latest) > parse_version(current)
        assets = [{'name': item['name'], 'size': item['size'], 'url': item['browser_download_url']}
                  for item in release.get('assets', []) if isinstance(item, dict)]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('GitHub sent an answer Tessera cannot read') from exc
    return {'current': current, 'latest': latest.lstrip('v'), 'newer': newer, 'page': release.get('html_url', ''),
            'notes': notes_excerpt(release.get('body')),
            'firmware': firmware_asset(assets, board),
            'host': next((item for item in assets if item['name'] == f'tessera-host-{latest}.zip'), None),
            'sums': next((item for item in assets if item['name'] == 'SHA256SUMS'), None)}


def download_firmware(info: dict, folder: Path, opener=_urlopen) -> Path:
    """Fetch the release's firmware package into `folder`, verified against SHA256SUMS."""
    firmware, sums = info.get('firmware'), info.get('sums')
    if not firmware or not sums:
        raise ValueError('That release has no firmware package with a checksum file')
    if not FIRMWARE_ASSET.fullmatch(firmware['name']):
        raise ValueError('Unexpected firmware file name')
    return _save_verified(firmware, sums, folder, opener, MAX_DOWNLOAD, 'firmware package')


def _save_verified(asset: dict, sums: dict, folder: Path, opener, limit: int, what: str) -> Path:
    """Fetch `asset` into `folder`; it is kept only when its SHA-256 is the one SHA256SUMS lists for it."""
    for url in (asset['url'], sums['url']):
        _check_host(url)
    listing, final = _open(sums['url'], opener, 64 * 1024)
    _check_host(final)
    expected = None
    for line in listing.decode('utf-8', 'replace').splitlines():
        digest, _, name = line.strip().partition('  ')
        if name.strip().lstrip('*') == asset['name'] and re.fullmatch(r'[0-9a-fA-F]{64}', digest):
            expected = digest.lower()
    if expected is None:
        raise ValueError(f'The checksum file does not list the {what}')
    data, final = _open(asset['url'], opener, limit)
    _check_host(final)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f'The {what.split()[0]} download is damaged (checksum mismatch); nothing was saved')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / asset['name']
    temporary = target.with_suffix('.part')
    temporary.write_bytes(data)
    temporary.replace(target)
    return target


def download_host(info: dict, folder: Path, opener=_urlopen) -> Path:
    """Fetch the release's program zip into `folder`, verified against SHA256SUMS."""
    host, sums = info.get('host'), info.get('sums')
    if not host or not sums:
        raise ValueError('That release has no program file with a checksum file')
    if not HOST_ASSET.fullmatch(host['name']):
        raise ValueError('Unexpected program file name')
    return _save_verified(host, sums, folder, opener, MAX_HOST_DOWNLOAD, 'program file')


def install_host(package: Path, root: Path) -> int:
    """Unpack a verified program zip over the program folder `root`; returns how many files were written.

    Only files the zip holds are written. The user's own files are never among them, and every name is checked
    before the first file is written, so a zip with one bad name changes nothing. A source checkout is left to git.
    """
    root = Path(root)
    if (root / '.git').exists():
        raise ValueError('This folder is a source checkout. Update it with git pull.')
    with zipfile.ZipFile(package) as archive:
        members = []
        for item in archive.infolist():
            top, _, relative = item.filename.partition('/')
            if item.is_dir() or not relative:
                continue
            parts = PurePosixPath(relative).parts
            if not top or '\\' in item.filename or ':' in relative or relative.startswith('/') or '..' in parts:
                raise ValueError(f'The update file has a name that is not allowed: {item.filename[:80]}')
            if not USER_FILES.fullmatch(relative):
                members.append((item, relative))
        names = {relative for _, relative in members}
        if not {'VERSION', 'host/tesserad.py'} <= names or len({item.filename.partition('/')[0] for item, _ in members}) != 1:
            raise ValueError('This is not a Tessera program file')
        if sum(item.file_size for item, _ in members) > MAX_UNPACKED:
            raise ValueError('The update file unpacks to more than expected')
        staged = []  # (new file, target); VERSION goes last, so a half-done update is never taken for a finished one
        try:
            for item, relative in sorted(members, key=lambda member: member[1] == 'VERSION'):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + '.new')
                staged.append((temporary, target))
                with archive.open(item) as source, open(temporary, 'wb') as out:
                    shutil.copyfileobj(source, out)
                mode = (item.external_attr >> 16) & 0o777
                if target.exists():
                    shutil.copymode(target, temporary)  # Tessera.sh stays a program the user can start
                elif mode:
                    os.chmod(temporary, mode)
            swapped = []  # (target, its old file or None), so a failure part-way puts every file back
            try:
                for temporary, target in staged:
                    backup = target.with_name(target.name + '.old') if target.is_file() else None
                    swapped.append((target, backup))
                    if backup:
                        os.replace(target, backup)
                    os.replace(temporary, target)
            except OSError:
                for target, backup in reversed(swapped):
                    try:
                        if backup:
                            os.replace(backup, target)
                        else:
                            target.unlink(missing_ok=True)
                    except OSError:
                        pass  # the original error is the one to report
                raise
            for _, backup in swapped:
                if backup:
                    backup.unlink(missing_ok=True)
        finally:
            for temporary, _ in staged:
                temporary.unlink(missing_ok=True)
    return len(members)
