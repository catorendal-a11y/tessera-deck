"""Generate the Tessera logo in docs/images: logo-mark.svg, logo.svg and logo.png.

The geometry matches the device header (main/ui/ui.cpp) and the editor (host/editor/app.js):
a 3x3 mosaic with its top-right tile broken loose, plus TESSERA drawn from rounded 5x7 tiles,
both swept across the mint -> cyan -> purple brand gradient.
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / 'docs' / 'images'
STOPS = ((88, 224, 155), (77, 208, 225), (179, 136, 255))
AMBER = (255, 183, 77)
GLYPHS = {
    'T': ('11111', '00100', '00100', '00100', '00100', '00100', '00100'),
    'E': ('11111', '10000', '10000', '11110', '10000', '10000', '11111'),
    'S': ('01111', '10000', '10000', '01110', '00001', '00001', '11110'),
    'R': ('11110', '10001', '10001', '11110', '10100', '10010', '10001'),
    'A': ('01110', '10001', '10001', '11111', '10001', '10001', '10001'),
}
WORD = 'TESSERA'
MARK_SIZE = 48
WORD_X, WORD_Y = 78, 5
PADDING = 4
WIDTH, HEIGHT = WORD_X + 7 * 32 - 2 + 2 * PADDING, 52 + 2 * PADDING


def sweep(t: float) -> tuple[int, int, int]:
    scaled = min(max(t, 0.0), 1.0) * 2
    index = min(int(scaled), 1)
    fraction = scaled - index
    return tuple(round(a + (b - a) * fraction) for a, b in zip(STOPS[index], STOPS[index + 1]))


def mark_tiles() -> list[tuple[float, float, float, float, tuple[int, int, int]]]:
    """x, y, size, radius, colour for every tile of the mark (origin = top-left of the 48 px box)."""
    tiles = [(col * 16, 4 + row * 16, 13, 4, sweep((row + col) / 4))
             for row in range(3) for col in range(3) if (row, col) != (0, 2)]
    tiles.append((34, 0, 12, 4, AMBER))
    return tiles


def word_tiles() -> list[tuple[float, float, float, float, tuple[int, int, int]]]:
    tiles = []
    for index, letter in enumerate(WORD):
        for row, line in enumerate(GLYPHS[letter]):
            for col, bit in enumerate(line):
                if bit == '1':
                    tiles.append((WORD_X + index * 32 + col * 6, WORD_Y + row * 6, 5, 2,
                                  sweep((index * 5 + col) / 34)))
    return tiles


def hex_color(rgb) -> str:
    return '#%02X%02X%02X' % tuple(rgb)


def svg_rects(tiles, dx=0, dy=0) -> str:
    return ''.join(f'<rect x="{x + dx}" y="{y + dy}" width="{size}" height="{size}" rx="{radius}" fill="{hex_color(color)}"/>'
                   for x, y, size, radius, color in tiles)


def write_svgs() -> None:
    mark = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {MARK_SIZE + 2 * PADDING} {MARK_SIZE + 2 * PADDING}" '
            f'role="img" aria-label="Tessera">{svg_rects(mark_tiles(), PADDING, PADDING)}</svg>\n')
    full = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="Tessera">'
            f'{svg_rects(mark_tiles() + word_tiles(), PADDING, PADDING)}</svg>\n')
    (OUT / 'logo-mark.svg').write_text(mark, encoding='utf-8')
    (OUT / 'logo.svg').write_text(full, encoding='utf-8')


def write_png(scale: int = 6) -> None:
    sheet = Image.new('RGBA', (WIDTH * scale, HEIGHT * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    for x, y, size, radius, color in mark_tiles() + word_tiles():
        left, top = (x + PADDING) * scale, (y + PADDING) * scale
        draw.rounded_rectangle((left, top, left + size * scale - 1, top + size * scale - 1),
                               radius=radius * scale, fill=tuple(color) + (255,))
    sheet.resize((WIDTH * 3, HEIGHT * 3), Image.LANCZOS).save(OUT / 'logo.png')


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_svgs()
    write_png()
    print('Wrote logo assets to', OUT)


if __name__ == '__main__':
    main()
