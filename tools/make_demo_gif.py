"""Builds docs/images/demo.gif: a short tour of the panel, drawn by the real firmware UI.

The frames come from the native build (tools/render_screens.py for the key pages, tests/native/test_ui for the
agents, mixer and clock screens) and the editor images in docs/images, so nothing is photographed. Usage, after both have run:

    host\\.venv\\Scripts\\python.exe tools\\make_demo_gif.py [screens folder] [previews folder] [output.gif]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
WIDTH, PANEL_HEIGHT, CAPTION_HEIGHT = 800, 469, 51
BACKGROUND, CARD, TEXT, ACCENT = '#0A0E10', '#12191D', '#EAF2EF', '#58E09B'
# file, caption, where a finger lands on the 1024 x 600 panel (or None). Keys sit at x 179 + 150 * column,
# y 152 + 172 * row; the rail buttons at x 42, y 111 + 60 * index.
SCENES = [
    ('screens/main__main.png', 'Your apps on 18 keys, with their real icons. A tap opens the app.', (179, 152)),
    ('screens/main__main.png', 'A key can open a folder: a page of its own', (779, 496)),
    ('screens/main__apps.png', 'Folders for games, Office and AI apps, with a key back', None),
    ('screens/main__system.png', 'Snap windows, switch desktops, lock the PC', (329, 152)),
    ('screens/main__audio.png', 'Media keys, volume and Bluetooth', None),
    ('screens/main__meetings.png', 'Mute Teams, Zoom and Discord from any window', (179, 152)),
    ('screens/coding__git.png', 'Pages follow the app in front: Git keys while you code', None),
    ('screens/Claude-Code__main.png', 'Claude Code and Codex commands, one tap each', (329, 152)),
    ('screens/main__widgets.png', 'Widgets on wide keys: clock, calendar, sound, CPU, GPU, memory, network', None),
    ('previews/question.ppm', 'Claude Code asks for permission. You answer on the panel.', (912, 145)),
    ('previews/agents.ppm', 'See what every AI agent is doing', (42, 231)),
    ('previews/mixer.ppm', 'A sound mixer with a fader per program', (553, 154)),
    ('screens/main__status.png', 'Live PC gauges: processor, graphics card, memory, disk, network', None),
    ('previews/ambient.ppm', 'Step away and a big clock shows the time and the weather', None),
    # the editor: the keys and the selected key's settings, cut out of the full window so the text stays readable
    ('docs/editor-main.png', 'Set it all up in the editor: drag apps and actions onto keys', None, (66, 56, 1716, 876)),
    ('docs/editor-widgets.png', 'Pick a widget and a size; the panel follows at once', None, (66, 56, 1716, 876)),
]


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ('segoeuib.ttf', 'DejaVuSans-Bold.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def scene(path: Path, caption: str, crop=None) -> Image.Image:
    frame = Image.new('RGB', (WIDTH, PANEL_HEIGHT + CAPTION_HEIGHT), BACKGROUND)
    picture = Image.open(path).convert('RGB')
    if crop:
        picture = picture.crop(crop)
    picture.thumbnail((WIDTH, PANEL_HEIGHT), Image.LANCZOS)  # the editor is wider than the panel: fit, do not stretch
    frame.paste(picture, ((WIDTH - picture.width) // 2, (PANEL_HEIGHT - picture.height) // 2))
    draw = ImageDraw.Draw(frame)
    draw.rectangle((0, PANEL_HEIGHT, WIDTH, PANEL_HEIGHT + CAPTION_HEIGHT), fill=CARD)
    draw.rectangle((0, PANEL_HEIGHT, 6, PANEL_HEIGHT + CAPTION_HEIGHT), fill=ACCENT)
    draw.text((24, PANEL_HEIGHT + CAPTION_HEIGHT // 2), caption, font=font(21), fill=TEXT, anchor='lm')
    return frame


def touched(frame: Image.Image, point: tuple[int, int], step: int, steps: int) -> Image.Image:
    """A ring that grows from the finger's position and fades."""
    x, y = point[0] * WIDTH / 1024, point[1] * PANEL_HEIGHT / 600
    layer = Image.new('RGBA', frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    radius, alpha = 14 + step * 9, int(230 * (1 - step / steps))
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=(255, 255, 255, alpha), width=5)
    draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(255, 255, 255, min(255, alpha + 25)))
    return Image.alpha_composite(frame.convert('RGBA'), layer).convert('RGB')


def main() -> int:
    screens = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'build/screens'
    previews = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / 'build/previews'
    output = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / 'docs/images/demo.gif'
    folders = {'screens': screens, 'previews': previews, 'docs': ROOT / 'docs/images'}
    stills = [scene(folders[name.split('/')[0]] / name.split('/')[1], caption, *rest) for name, caption, _, *rest in SCENES]
    frames, durations = [], []
    for index, still in enumerate(stills):
        point = SCENES[index][2]
        frames.append(still)
        durations.append(1500 if point else 2300)
        if point:
            for step in range(5):
                frames.append(touched(still, point, step, 5))
                durations.append(80)
            frames.append(still)
            durations.append(500)
        following = stills[(index + 1) % len(stills)]
        for step in (1, 2, 3):
            frames.append(Image.blend(still, following, step / 4))
            durations.append(60)
    palette = [frame.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for frame in frames]
    palette[0].save(output, save_all=True, append_images=palette[1:], duration=durations, loop=0, optimize=True)
    print(f'{output}: {len(frames)} frames, {sum(durations) / 1000:.1f} s, {output.stat().st_size / 1e6:.1f} MB')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
