"""Bounded, content-addressed button images. No user paths cross the HTTP API."""
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import struct
import warnings

SIZE = 72
MAX_FRAMES = 12
ID = re.compile(r'im:[0-9a-f]{12}\Z')


class Assets:
    def __init__(self, profiles):
        self.root = Path(profiles).parent / 'assets'

    def read(self, name):
        if not ID.fullmatch(name):
            raise ValueError('Ugyldig bilde-ID')
        return (self.root / (name[3:] + '.adimg')).read_bytes()

    def preview(self, name):
        if not ID.fullmatch(name):
            raise ValueError('Ugyldig bilde-ID')
        return (self.root / (name[3:] + '.png')).read_bytes()

    def import_image(self, data):
        from PIL import Image, ImageOps
        raw = base64.b64decode(data, validate=True)
        if not raw or len(raw) > 8 * 1024 * 1024:
            raise ValueError('Bruk en bildefil på høyst 8 MB')
        frames, durations = [], []
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as image:
                    if image.format not in ('PNG', 'JPEG', 'GIF', 'WEBP') or image.width * image.height > 16_000_000:
                        raise ValueError('Bruk PNG, JPEG, GIF eller WebP, høyst 16 megapiksler')
                    count = getattr(image, 'n_frames', 1)
                    if count > 240:
                        raise ValueError('Animasjonen kan ha høyst 240 bilder')
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
                Image.DecompressionBombWarning, OSError) as exc:
            raise ValueError('Bildet kunne ikke leses som PNG, JPEG, GIF eller WebP') from exc
        blob = bytearray(b'ADI1' + bytes((SIZE, SIZE, len(frames))))
        for frame, duration in zip(frames, durations):
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
        (self.root / (name + '.adimg')).write_bytes(blob)
        frames[0].save(self.root / (name + '.png'), save_all=len(frames) > 1,
                       append_images=frames[1:], duration=durations, loop=0)
        return {'id': 'im:' + name, 'frames': len(frames), 'sampled': count > MAX_FRAMES,
                'width': SIZE, 'height': SIZE}

    def import_program_icon(self, path):
        """Import the icon Windows associates with an executable or shortcut."""
        import os
        if os.name != 'nt':
            raise ValueError('Programikoner støttes bare på Windows')
        import ctypes
        from ctypes import wintypes
        from PIL import Image

        class SHFILEINFOW(ctypes.Structure):
            _fields_ = [('hIcon', wintypes.HICON), ('iIcon', ctypes.c_int),
                        ('dwAttributes', wintypes.DWORD), ('szDisplayName', wintypes.WCHAR * 260),
                        ('szTypeName', wintypes.WCHAR * 80)]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG),
                        ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                        ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                        ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                        ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                        ('biClrImportant', wintypes.DWORD)]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', wintypes.DWORD * 3)]

        shell32, user32, gdi32 = ctypes.windll.shell32, ctypes.windll.user32, ctypes.windll.gdi32
        info = SHFILEINFOW()
        if not shell32.SHGetFileInfoW(str(path), 0, ctypes.byref(info), ctypes.sizeof(info), 0x100 | 0):
            raise ValueError('Windows fant ikke et ikon for programmet')
        screen = user32.GetDC(0)
        memory = gdi32.CreateCompatibleDC(screen)
        bits = ctypes.c_void_p()
        bitmap_info = BITMAPINFO(BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), SIZE, -SIZE,
                                 1, 32, 0, SIZE * SIZE * 4, 0, 0, 0, 0))
        bitmap = gdi32.CreateDIBSection(memory, ctypes.byref(bitmap_info), 0, ctypes.byref(bits), None, 0)
        old = gdi32.SelectObject(memory, bitmap)
        try:
            if not user32.DrawIconEx(memory, 0, 0, info.hIcon, SIZE, SIZE, 0, None, 3):
                raise ValueError('Programikonet kunne ikke tegnes')
            raw = ctypes.string_at(bits, SIZE * SIZE * 4)
            image = Image.frombytes('RGBA', (SIZE, SIZE), raw, 'raw', 'BGRA')
            output = BytesIO()
            image.save(output, format='PNG')
            return self.import_image(base64.b64encode(output.getvalue()).decode())
        finally:
            gdi32.SelectObject(memory, old)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory)
            user32.ReleaseDC(0, screen)
            user32.DestroyIcon(info.hIcon)

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
        return {name: base64.b64encode(self.preview(name)).decode() for name in names}
