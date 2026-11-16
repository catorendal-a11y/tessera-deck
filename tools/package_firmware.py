"""Package an ESP-IDF build as dist/tessera-firmware[-<board>]-<version>.zip (images + manifest + checksum)."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from firmware_update import BOARD_CHIPS, BOARD_ID, OTADATA_NAME, build_package  # noqa: E402


def has_ota_slots(partition_table: bytes) -> bool:
    """True when the binary partition table has an otadata entry (type data, subtype ota)."""
    entries = (partition_table[start:start + 32] for start in range(0, len(partition_table) - 31, 32))
    return any(entry[:2] == b'\xaa\x50' and entry[2:4] == b'\x01\x00' for entry in entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build_dir', type=Path)
    parser.add_argument('out_dir', type=Path)
    parser.add_argument('--board', default=BOARD_ID, choices=sorted(BOARD_CHIPS))
    args = parser.parse_args()
    chip = BOARD_CHIPS[args.board]
    description = args.build_dir / 'project_description.json'
    if description.is_file():
        target = json.loads(description.read_text(encoding='utf-8')).get('target')
        if target and target != chip:
            sys.exit(f'The build is for {target}, but {args.board} needs {chip}')
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    header = (ROOT / 'main' / 'protocol_version.h').read_text(encoding='utf-8')
    protocol = int(re.search(r'#define\s+TESSERA_PROTOCOL\s+(\d+)', header).group(1))
    # The A/B table needs the OTA data image in the package, or an esptool app install would keep an old slot.
    flash_files = json.loads((args.build_dir / 'flasher_args.json').read_text(encoding='utf-8'))['flash_files']
    table = next((args.build_dir / name for name in flash_files.values() if Path(name).name == 'partition-table.bin'), None)
    has_slots = table is not None and has_ota_slots(table.read_bytes())
    if has_slots and not any(Path(name).name == OTADATA_NAME for name in flash_files.values()):
        sys.exit(f'{OTADATA_NAME} is missing from the build; run a full idf.py build first')
    target = build_package(args.build_dir, args.out_dir, version, protocol, args.board, chip)
    print(f'Wrote {target} (board {args.board}, version {version}, protocol {protocol})')


if __name__ == '__main__':
    main()
