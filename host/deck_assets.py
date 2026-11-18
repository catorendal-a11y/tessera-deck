"""Bounded, content-addressed button images. No user paths cross the HTTP API."""
import base64
from platform_support import load
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import struct
import time
import warnings

from config_store import write_atomic

SIZE = 72
MAX_FRAMES = 12
AUTO_ICON = 'app'
ID = re.compile(r'im:[0-9a-f]{12}\Z')
RETRY_SECONDS = 60  # a program icon that could not be read is tried again after this long


def is_remote_target(target):
    r"""A share (\\host\s, //host/s, \\host@80\s), \\?\UNC\ path or URL, which the shell reaches over the network.

    Looking one up sends the user's Windows (NTLM) sign-in to that host, so icons are never read from one.
    """
    import os
    text = os.path.expandvars(target.strip()).replace('/', '\\')
    if text.startswith('\\\\'):
        return not re.match(r'\\\\\?\\[A-Za-z]:\\', text)  # \\?\C:\... is a long local path
    scheme = re.match(r'([A-Za-z][A-Za-z0-9+.-]+):', text)  # one letter is a drive
    return bool(scheme) and scheme.group(1).lower() != 'shell'


class Assets:
    def __init__(self, profiles):
        self.root = Path(profiles).parent / 'assets'
        self._resolved = {}

    def read(self, name):
        if not ID.fullmatch(name):
            raise ValueError('Invalid image ID')
        return (self.root / (name[3:] + '.adimg')).read_bytes()

    def preview(self, name):
        if not ID.fullmatch(name):
            raise ValueError('Invalid image ID')
        return (self.root / (name[3:] + '.png')).read_bytes()

    def import_image(self, data):
        from PIL import Image, ImageOps
        raw = base64.b64decode(data, validate=True)
        if not raw or len(raw) > 8 * 1024 * 1024:
            raise ValueError('Use an image file of at most 8 MB')
        frames, durations = [], []
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                # formats= keeps every other Pillow decoder (EPS, TGA, ...) away from a file the user drops in
                with Image.open(BytesIO(raw), formats=('PNG', 'JPEG', 'GIF', 'WEBP')) as image:
                    if image.format not in ('PNG', 'JPEG', 'GIF', 'WEBP') or image.width * image.height > 16_000_000:
                        raise ValueError('Use PNG, JPEG, GIF or WebP, at most 16 megapixels')
                    count = getattr(image, 'n_frames', 1)
                    if count > 240:
                        raise ValueError('The animation can have at most 240 frames')
                    step = max(1, (count + MAX_FRAMES - 1) // MAX_FRAMES)
                    for index in range(count):
                        image.seek(index)
                        duration = max(40, min(10000, int(image.info.get('duration', 100))))
                        if index % step == 0:
                            canvas = Image.new('RGBA', (SIZE, SIZE))
                            frame = ImageOps.exif_transpose(image).convert('RGBA')
                            frame.thumbnail((SIZE, SIZE), Image.Resampling.LANCZOS)
                            canvas.alpha_composite(frame, ((SIZE-frame.width)//2, (SIZE-frame.height)//2))
                            frames.append(canvas)
                            durations.append(duration)
                        else:
                            durations[-1] = min(60000, durations[-1] + duration)
        except (Image.UnidentifiedImageError, Image.DecompressionBombError,
                Image.DecompressionBombWarning, OSError, SyntaxError, IndexError, EOFError, struct.error) as exc:
            raise ValueError('The image could not be read as PNG, JPEG, GIF or WebP') from exc
        blob = bytearray(b'ADI1' + bytes((SIZE, SIZE, len(frames))))
        for frame, duration in zip(frames, durations, strict=False):
            pixels = frame.tobytes('raw', 'BGRA')
            encoded = bytearray()
            at = 0
            while at < len(pixels):
                pixel = pixels[at:at+4]
                run = 1
                while run < 255 and at + 4*run < len(pixels) and pixels[at+4*run:at+4*run+4] == pixel:
                    run += 1
                encoded.extend(bytes((run,)) + pixel)
                at += 4*run
            blob.extend(struct.pack('<HI', duration, len(encoded)))
            blob.extend(encoded)
        name = hashlib.sha256(blob).hexdigest()[:12]
        self.root.mkdir(parents=True, exist_ok=True)
        # The name is the content's hash, so a file that exists already holds these bytes. Rewriting it in place
        # (editor and daemon both re-import program icons) could let push_assets read a half-written image.
        image_file, preview_file = self.root / (name + '.adimg'), self.root / (name + '.png')
        try:  # a copy cut short by an older, non-atomic write has the right name but too few bytes
            complete = image_file.stat().st_size == len(blob)
        except OSError:
            complete = False
        if not complete:
            write_atomic(image_file, bytes(blob))
        if not preview_file.is_file():
            output = BytesIO()
            frames[0].save(output, format='PNG', save_all=len(frames) > 1,
                           append_images=frames[1:], duration=durations, loop=0)
            write_atomic(preview_file, output.getvalue())
        return {'id': 'im:' + name, 'frames': len(frames), 'sampled': count > MAX_FRAMES,
                'width': SIZE, 'height': SIZE}

    def exists(self, name):
        return bool(ID.fullmatch(name)) and (self.root / (name[3:] + '.adimg')).is_file()

    def rebuild_from_actions(self, button):
        """Import the program icon of the button's open action, else None."""
        target = next((a['target'] for a in button.get('actions', [])
                       if a.get('type') == 'open' and isinstance(a.get('target'), str)), None)
        # Runs on every push without a key press, for imported profiles too: no network shares or URLs.
        if target is None or is_remote_target(target):
            return None
        try:
            return self.import_program_icon(target)['id']
        except (ValueError, OSError):
            return None

    def icon_for(self, button):
        """Resolve a button icon to something the panel can show.

        'app' means the program icon of the button's open action; an im: image whose
        file is missing (fresh checkout, deleted assets) is rebuilt the same way.
        Anything else is returned unchanged. Failures fall back to the default icon.
        """
        icon = button.get('icon', 'ok')
        missing = bool(ID.fullmatch(icon)) and not self.exists(icon)
        if icon != AUTO_ICON and not missing:
            return icon
        key = (icon, json.dumps(button.get('actions', []), sort_keys=True))
        cached = self._resolved.get(key)
        if cached is None or cached[1] < time.monotonic():
            found = self.rebuild_from_actions(button)
            cached = self._resolved[key] = (found or 'ok', float('inf') if found else time.monotonic() + RETRY_SECONDS)
        return cached[0]

    def heal(self, config):
        """Copy of config with every 'app' or missing im: icon resolved via icon_for."""
        def visit(value):
            if isinstance(value, list):
                return [visit(item) for item in value]
            if not isinstance(value, dict):
                return value
            result = {key: visit(item) for key, item in value.items()}
            if isinstance(result.get('icon'), str):
                healed = self.icon_for(result)
                # The editor saves what heal returns: a missing image keeps its id (its file may still be
                # copied over) instead of becoming the 'ok' fallback, which would lose the reference for good.
                if result['icon'] == AUTO_ICON or healed.startswith('im:'):
                    result['icon'] = healed
            return result
        return visit(config)

    def import_program_icon(self, target):
        """Import a crisp app icon for a program, shortcut, Store app or PATH alias.

        The shell renders a 256 px icon with alpha, which is downscaled to the
        panel size. The older 32 px path remains as a fallback for odd targets.
        """
        image = load('icons').program_icon_image(target)
        output = BytesIO()
        image.save(output, format='PNG')
        return self.import_image(base64.b64encode(output.getvalue()).decode())


    def export(self, config):
        names = set()
        def visit(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == 'icon' and isinstance(item, str) and ID.fullmatch(item):
                        names.add(item)
                    else:
                        visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
        visit(config)
        images = {}
        for name in names:
            try:
                images[name] = base64.b64encode(self.preview(name)).decode()
            except OSError:  # no file for this id: the rest of the profile still exports
                pass
        return images
