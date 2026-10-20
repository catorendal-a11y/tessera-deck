#!/usr/bin/env python3
"""Regenerate host/tessera.ico from the tray mark, so every surface shows the same icon.

Run with the host environment:  host\\.venv\\Scripts\\python.exe tools\\make_icon.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from tessera_tray import make_icon  # noqa: E402

SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]


def main():
    target = ROOT / 'host' / 'tessera.ico'
    make_icon('connected', 256).save(target, format='ICO', sizes=SIZES)
    print(f'Wrote {target} with {len(SIZES)} sizes')


if __name__ == '__main__':
    main()
