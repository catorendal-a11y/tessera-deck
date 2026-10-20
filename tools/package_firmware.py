"""Package an ESP-IDF build as dist/tessera-firmware-<version>.zip (images + manifest + checksum)."""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from firmware_update import build_package  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build_dir', type=Path)
    parser.add_argument('out_dir', type=Path)
    args = parser.parse_args()
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    header = (ROOT / 'main' / 'protocol_version.h').read_text(encoding='utf-8')
    protocol = int(re.search(r'#define\s+TESSERA_PROTOCOL\s+(\d+)', header).group(1))
    target = build_package(args.build_dir, args.out_dir, version, protocol)
    print(f'Wrote {target} (version {version}, protocol {protocol})')


if __name__ == '__main__':
    main()
