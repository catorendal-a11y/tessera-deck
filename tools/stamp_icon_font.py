"""Retain Lucide/Feather notices in the generated glyph source."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / 'main/ui/fonts/deck_lucide_60.c'
marker = '/* Lucide 1.59.0 icon outlines; original license notices follow.\n'
source = path.read_text(encoding='utf-8')
if not source.startswith(marker):
    license_text = (root / 'vendor/lucide/LICENSE').read_text(encoding='utf-8')
    path.write_text(marker + license_text + '\n*/\n' + source, encoding='utf-8')
