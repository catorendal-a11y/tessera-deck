"""Bounded, content-addressed button images. No user paths cross the HTTP API."""
import base64
import ctypes
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import struct
import warnings

SIZE = 72
MAX_FRAMES = 12
AUTO_ICON = 'app'
ID = re.compile(r'im:[0-9a-f]{12}\Z')


SHELL_ICON_SIZE = 256
SIIGBF_BIGGERSIZEOK, SIIGBF_ICONONLY = 0x1, 0x4
COINIT_APARTMENTTHREADED = 0x2
RPC_E_CHANGED_MODE = -2147417850
IID_ISHELLITEMIMAGEFACTORY = 'bcc18b79-ba16-442f-80c4-8a59c30c463b'
# PATH aliases are zero-byte reparse points, so the shell cannot draw them.
PROGRAM_ALIASES = {'wt.exe': 'shell:AppsFolder\\Microsoft.WindowsTerminal_8wekyb3d8bbwe!App'}


def resolve_program_target(target):
    """Expand variables and PATH names so the shell can find the program."""
    import os
    import shutil
    if not isinstance(target, str) or not target.strip():
        raise ValueError('Choose a valid program')
    target = os.path.expandvars(target.strip())
    if target.lower().startswith('shell:'):
        return target
    if target.lower() in PROGRAM_ALIASES:
        return PROGRAM_ALIASES[target.lower()]
    if not os.path.isabs(target):
        target = shutil.which(target) or target
    return target


def _com_guid(text):
    import ctypes
    import uuid

    class GUID(ctypes.Structure):
        _fields_ = [('data1', ctypes.c_uint32), ('data2', ctypes.c_uint16),
                    ('data3', ctypes.c_uint16), ('data4', ctypes.c_ubyte * 8)]
    value = uuid.UUID(text)
    guid = GUID(value.time_low, value.time_mid, value.time_hi_version)
    for index, byte in enumerate(value.bytes[8:]):
        guid.data4[index] = byte
    return guid


def _hbitmap_to_image(hbitmap):
    import ctypes
    from ctypes import wintypes
    from PIL import Image

    class BITMAP(ctypes.Structure):
        _fields_ = [('type', wintypes.LONG), ('width', wintypes.LONG), ('height', wintypes.LONG),
                    ('width_bytes', wintypes.LONG), ('planes', wintypes.WORD),
                    ('bits_per_pixel', wintypes.WORD), ('bits', ctypes.c_void_p)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('width', wintypes.LONG), ('height', wintypes.LONG),
                    ('planes', wintypes.WORD), ('bit_count', wintypes.WORD),
                    ('compression', wintypes.DWORD), ('size_image', wintypes.DWORD),
                    ('x_ppm', wintypes.LONG), ('y_ppm', wintypes.LONG),
                    ('colors_used', wintypes.DWORD), ('colors_important', wintypes.DWORD)]

    gdi32, user32 = ctypes.WinDLL('gdi32'), ctypes.WinDLL('user32')
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
    bitmap = BITMAP()
    gdi32.GetObjectW(hbitmap, ctypes.sizeof(bitmap), ctypes.byref(bitmap))
    width, height = bitmap.width, bitmap.height
    if bitmap.bits_per_pixel != 32 or not 0 < width <= 1024 or not 0 < height <= 1024:
        raise ValueError('Uventet ikonformat fra Windows')
    header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = ctypes.create_string_buffer(width * height * 4)
    screen = user32.GetDC(None)
    try:
        if not gdi32.GetDIBits(screen, hbitmap, 0, height, pixels, ctypes.byref(header), 0):
            raise OSError('Could not read the icon image')
    finally:
        user32.ReleaseDC(None, screen)
    return Image.frombuffer('RGBA', (width, height), pixels, 'raw', 'BGRA', 0, 1).copy()


def shell_item_image(target, size=SHELL_ICON_SIZE):
    """Render a shell item's icon (file, shortcut, shell:AppsFolder id) as RGBA."""
    import os
    if os.name != 'nt':
        raise ValueError('Program icons are only supported on Windows')
    import ctypes
    from ctypes import wintypes

    class SIZE(ctypes.Structure):
        _fields_ = [('cx', wintypes.LONG), ('cy', wintypes.LONG)]

    ole32, shell32 = ctypes.WinDLL('ole32'), ctypes.WinDLL('shell32')
    gdi32 = ctypes.WinDLL('gdi32')
    started = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    if started < 0 and started != RPC_E_CHANGED_MODE:
        raise OSError('Could not start COM')
    factory, hbitmap = ctypes.c_void_p(), wintypes.HBITMAP()
    try:
        guid = _com_guid(IID_ISHELLITEMIMAGEFACTORY)
        shell32.SHCreateItemFromParsingName.argtypes = [
            wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        if shell32.SHCreateItemFromParsingName(target, None, ctypes.byref(guid), ctypes.byref(factory)) < 0:
            raise ValueError('Windows could not find the program')
        table = ctypes.cast(ctypes.cast(factory, ctypes.POINTER(ctypes.c_void_p))[0],
                            ctypes.POINTER(ctypes.c_void_p))
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])
        get_image = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, SIZE, wintypes.UINT,
                                       ctypes.POINTER(wintypes.HBITMAP))(table[3])
        try:
            result = get_image(factory, SIZE(size, size), SIIGBF_BIGGERSIZEOK | SIIGBF_ICONONLY,
                               ctypes.byref(hbitmap))
        finally:
            release(factory)
        if result < 0 or not hbitmap:
            raise ValueError('Windows could not draw the icon')
        try:
            return _hbitmap_to_image(hbitmap)
        finally:
            gdi32.DeleteObject(hbitmap)
    finally:
        if started >= 0:
            ole32.CoUninitialize()


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
                with Image.open(BytesIO(raw)) as image:
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
                Image.DecompressionBombWarning, OSError) as exc:
            raise ValueError('The image could not be read as PNG, JPEG, GIF or WebP') from exc
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

    def exists(self, name):
        return bool(ID.fullmatch(name)) and (self.root / (name[3:] + '.adimg')).is_file()

    def rebuild_from_actions(self, button):
        """Import the program icon of the button's open action, else None."""
        target = next((a['target'] for a in button.get('actions', [])
                       if a.get('type') == 'open' and isinstance(a.get('target'), str)), None)
        if target is None:
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
        if key not in self._resolved:
            self._resolved[key] = self.rebuild_from_actions(button) or 'ok'
        return self._resolved[key]

    def heal(self, config):
        """Copy of config with every 'app' or missing im: icon resolved via icon_for."""
        def visit(value):
            if isinstance(value, list):
                return [visit(item) for item in value]
            if not isinstance(value, dict):
                return value
            result = {key: visit(item) for key, item in value.items()}
            if isinstance(result.get('icon'), str):
                result['icon'] = self.icon_for(result)
            return result
        return visit(config)

    def import_program_icon(self, target):
        """Import a crisp app icon for a program, shortcut, Store app or PATH alias.

        The shell renders a 256 px icon with alpha, which is downscaled to the
        panel size. The older 32 px path remains as a fallback for odd targets.
        """
        resolved = resolve_program_target(target)
        try:
            image = shell_item_image(resolved)
        except (OSError, ValueError, ctypes.ArgumentError):
            return self._import_program_icon_legacy(resolved)
        output = BytesIO()
        image.save(output, format='PNG')
        return self.import_image(base64.b64encode(output.getvalue()).decode())

    def _import_program_icon_legacy(self, path):
        """Import the icon Windows associates with an executable or shortcut."""
        import os
        if os.name != 'nt':
            raise ValueError('Program icons are only supported on Windows')
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
            raise ValueError('Windows found no icon for the program')
        screen = user32.GetDC(0)
        memory = gdi32.CreateCompatibleDC(screen)
        bits = ctypes.c_void_p()
        bitmap_info = BITMAPINFO(BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), SIZE, -SIZE,
                                 1, 32, 0, SIZE * SIZE * 4, 0, 0, 0, 0))
        bitmap = gdi32.CreateDIBSection(memory, ctypes.byref(bitmap_info), 0, ctypes.byref(bits), None, 0)
        old = gdi32.SelectObject(memory, bitmap)
        try:
            if not user32.DrawIconEx(memory, 0, 0, info.hIcon, SIZE, SIZE, 0, None, 3):
                raise ValueError('The program icon could not be drawn')
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
