"""User-initiated update check against the project's GitHub releases, and a verified firmware download.

Nothing is contacted until the user presses the button. Only the project's own release API and GitHub's
download hosts are used, downloads are limited in size, and a firmware package is kept only when its
SHA-256 matches the SHA256SUMS file published with the same release.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

REPOSITORY = 'catorendal-a11y/tessera-deck'
RELEASE_API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
DOWNLOAD_HOSTS = ('github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com')
TIMEOUT_SECONDS = 10
MAX_DOWNLOAD = 16 * 1024 * 1024
VERSION = re.compile(r'v?(\d+)\.(\d+)\.(\d+)')
FIRMWARE_ASSET = re.compile(r'tessera-firmware-[0-9A-Za-z.\-]+\.zip')


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


def check(current: str, opener=urllib.request.urlopen) -> dict:
    """Compare `current` with the latest published release."""
    raw, _ = _open(RELEASE_API, opener, 512 * 1024)
    try:
        release = json.loads(raw)
        latest = release['tag_name']
        newer = parse_version(latest) > parse_version(current)
        assets = [{'name': item['name'], 'size': item['size'], 'url': item['browser_download_url']}
                  for item in release.get('assets', []) if isinstance(item, dict)]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('GitHub sent an answer Tessera cannot read') from exc
    return {'current': current, 'latest': latest.lstrip('v'), 'newer': newer, 'page': release.get('html_url', ''),
            'firmware': next((item for item in assets if FIRMWARE_ASSET.fullmatch(item['name'])), None),
            'sums': next((item for item in assets if item['name'] == 'SHA256SUMS'), None)}


def download_firmware(info: dict, folder: Path, opener=urllib.request.urlopen) -> Path:
    """Fetch the release's firmware package into `folder`, verified against SHA256SUMS."""
    firmware, sums = info.get('firmware'), info.get('sums')
    if not firmware or not sums:
        raise ValueError('That release has no firmware package with a checksum file')
    if not FIRMWARE_ASSET.fullmatch(firmware['name']):
        raise ValueError('Unexpected firmware file name')
    for url in (firmware['url'], sums['url']):
        _check_host(url)
    listing, final = _open(sums['url'], opener, 64 * 1024)
    _check_host(final)
    expected = None
    for line in listing.decode('utf-8', 'replace').splitlines():
        digest, _, name = line.strip().partition('  ')
        if name.strip().lstrip('*') == firmware['name'] and re.fullmatch(r'[0-9a-fA-F]{64}', digest):
            expected = digest.lower()
    if expected is None:
        raise ValueError('The checksum file does not list the firmware package')
    data, final = _open(firmware['url'], opener, MAX_DOWNLOAD)
    _check_host(final)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('The firmware download is damaged (checksum mismatch); nothing was saved')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / firmware['name']
    temporary = target.with_suffix('.part')
    temporary.write_bytes(data)
    temporary.replace(target)
    return target
