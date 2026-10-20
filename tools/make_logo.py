"""Generate the Tessera logo assets in docs/images (mark SVG + wordmark PNGs)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / 'docs' / 'images'
PLATE = (23, 35, 41)
TILES = ((88, 224, 155), (77, 208, 225), (179, 136, 255), (255, 183, 77))
FONT = Path(r'C:\Windows\Fonts\segoeuib.ttf')


def hex_color(rgb):
    return '#%02X%02X%02X' % rgb


def mark_svg() -> str:
    cells = ''.join(
        f'<rect x="{24 + (i % 2) * 40}" y="{24 + (i // 2) * 40}" width="36" height="36" rx="10" fill="{hex_color(c)}"/>'
        for i, c in enumerate(TILES))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128" role="img" '
            f'aria-label="Tessera"><rect width="128" height="128" rx="30" fill="{hex_color(PLATE)}"/>{cells}</svg>\n')


def draw_mark(draw: ImageDraw.ImageDraw, x: int, y: int, size: int) -> None:
    unit = size / 128
    draw.rounded_rectangle((x, y, x + size, y + size), radius=30 * unit, fill=PLATE)
    for i, color in enumerate(TILES):
        left = x + (24 + (i % 2) * 40) * unit
        top = y + (24 + (i // 2) * 40) * unit
        draw.rounded_rectangle((left, top, left + 36 * unit, top + 36 * unit), radius=10 * unit, fill=color)


def banner(text_color, background) -> Image.Image:
    scale, height, width = 2, 160, 620
    image = Image.new('RGBA', (width * scale, height * scale), background)
    draw = ImageDraw.Draw(image)
    draw_mark(draw, 24 * scale, 16 * scale, 128 * scale)
    font = ImageFont.truetype(str(FONT), 76 * scale)
    x, y = 180 * scale, 80 * scale
    for letter in 'TESSERA':
        draw.text((x, y), letter, font=font, fill=text_color, anchor='lm')
        x += font.getlength(letter) + 8 * scale
    return image.resize((width, height), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'logo-mark.svg').write_text(mark_svg(), encoding='utf-8')
    banner((23, 35, 41), (0, 0, 0, 0)).save(OUT / 'logo-light.png')
    banner((232, 244, 239), (0, 0, 0, 0)).save(OUT / 'logo-dark.png')
    print('Wrote logo assets to', OUT)


if __name__ == '__main__':
    main()
