"""Draws every page of every profile with the real panel UI (tests/native/render_screens.cpp).

Usage: host\\.venv\\Scripts\\python.exe tools\\render_screens.py [profiles.json] [output folder] [path to render_screens]
Nothing is sent to the panel and the profile file is only read. Sensor values are read from this PC.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
import types
from unittest.mock import Mock
import zlib

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck  # noqa: E402

# The panel's clock in the renderer is the fixed 14:32 on Tue 20 Oct 2026 (render_screens.cpp); the clock widget and
# $(time) on the keys show the same moment, so one image never shows two different times.
SHOWN_AT = deck.datetime(2026, 10, 20, 14, 32)


class _Clock(deck.datetime):
    @classmethod
    def now(cls, tz=None):
        return SHOWN_AT


deck.datetime = _Clock
_strftime = time.strftime
time.strftime = lambda fmt, moment=None: _strftime(fmt, moment or SHOWN_AT.timetuple())


def safe(name: str) -> str:
    return ''.join(c if c.isalnum() else '-' for c in name)


def contact_sheet(shots: list[tuple[str, Path]], path: Path, columns: int = 3) -> None:
    width, height, title = 640, 375, 30
    rows = (len(shots) + columns - 1) // columns
    sheet = Image.new('RGB', (columns * (width + 12) + 12, rows * (height + title + 12) + 12), '#202020')
    draw = ImageDraw.Draw(sheet)
    for index, (name, image) in enumerate(shots):
        x, y = 12 + index % columns * (width + 12), 12 + index // columns * (height + title + 12)
        draw.text((x + 2, y + 8), name, fill='#f2f2f2')
        sheet.paste(Image.open(image).resize((width, height), Image.LANCZOS), (x, y + title))
    sheet.save(path)


def main() -> int:
    profiles = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'host/profiles.json'
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / 'build/screens'
    renderer = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / 'build/native/render_screens.exe'
    output.mkdir(parents=True, exist_ok=True)
    daemon = deck.Daemon(types.SimpleNamespace(profiles=str(profiles), port='RENDER', verbose=False, no_focus=True, deck_only=True))
    daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
    daemon.stats.sample()
    time.sleep(1.2)  # rates and Windows counters need two readings
    daemon.stats.sample()
    lines, shots, images = [], [], set()
    for profile, content in daemon.config['profiles'].items():
        for number, page in enumerate(content['pages']):
            daemon.profile, daemon.page = profile, page
            buttons = daemon.current_buttons()
            for name in sorted({b['icon'] for b in buttons if b['icon'].startswith('im:')} - images):
                raw = daemon.assets.read(name)
                blob = output / (name.replace(':', '_') + '.bin')
                blob.write_bytes(raw)
                lines.append(f'image\t{name}\t{zlib.crc32(raw)}\t{blob}')
                images.add(name)
            stem = output / f'{safe(profile)}__{safe(page)}'
            layout = stem.with_suffix('.json')
            layout.write_text(json.dumps({'buttons': buttons}, ensure_ascii=False), encoding='utf-8')
            lines.append(f'screen\t{stem.with_suffix(".ppm")}\t{layout}\t{profile.upper()}\t{page.upper()}\t{int(number > 0)}')
            shots.append((f'{profile} / {page}', stem))
    manifest = output / 'manifest.txt'
    manifest.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    result = subprocess.run([str(renderer), str(manifest)], check=False)
    converted = []
    for name, stem in shots:
        png = stem.with_suffix('.png')
        Image.open(stem.with_suffix('.ppm')).save(png)
        stem.with_suffix('.ppm').unlink()
        stem.with_suffix('.json').unlink()
        converted.append((name, png))
    for blob in output.glob('im_*.bin'):
        blob.unlink()
    manifest.unlink()
    contact_sheet(converted, output / 'all-screens.png')
    print(f'{len(converted)} screens in {output}')
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
