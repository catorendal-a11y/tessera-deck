"""Package an ESP-IDF build as dist/tessera-firmware-<version>.zip (images + manifest + checksum)."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from firmware_update import OTADATA_NAME, build_package  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build_dir', type=Path)
    parser.add_argument('out_dir', type=Path)
    args = parser.parse_args()
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    header = (ROOT / 'main' / 'protocol_version.h').read_text(encoding='utf-8')
    protocol = int(re.search(r'#define\s+TESSERA_PROTOCOL\s+(\d+)', header).group(1))
    # The A/B table needs the OTA data image in the package, or an esptool app install would keep an old slot.
    flash_files = json.loads((args.build_dir / 'flasher_args.json').read_text(encoding='utf-8'))['flash_files']
    has_slots = 'otadata' in (ROOT / 'partitions.csv').read_text(encoding='utf-8')
    if has_slots and not any(Path(name).name == OTADATA_NAME for name in flash_files.values()):
        sys.exit(f'{OTADATA_NAME} is missing from the build; run a full idf.py build first')
    target = build_package(args.build_dir, args.out_dir, version, protocol)
    print(f'Wrote {target} (version {version}, protocol {protocol})')


if __name__ == '__main__':
    main()
