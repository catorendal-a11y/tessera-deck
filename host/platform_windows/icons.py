"""Program icons on Windows: the shell's 256 px icon of a program, shortcut, Store app or PATH alias (COM and GDI)."""
import ctypes

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
    from platform_windows.programs import locate
    target = os.path.expandvars(target.strip())
    if target.lower().startswith('shell:'):
        return target
    if target.lower() in PROGRAM_ALIASES:
        return PROGRAM_ALIASES[target.lower()]
    if not os.path.isabs(target):
        target = shutil.which(target) or target
    elif not os.path.exists(target):
        target = locate(target) or target  # the program moved: another drive, version folder ...
    return target


def _com_guid(text):
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
        raise ValueError('Windows returned an unexpected icon format')
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


def legacy_icon_image(path):
    """The icon Windows associates with an executable or shortcut, as a 72 px image, through the older GDI path."""
    from deck_assets import SIZE
    import os
    if os.name != 'nt':
        raise ValueError('Program icons are only supported on Windows')
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
        return image
    finally:
        gdi32.SelectObject(memory, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(0, screen)
        user32.DestroyIcon(info.hIcon)


def program_icon_image(target):
    """The icon of a program, shortcut or Store app as an image: the shell's 256 px icon, else the older 32 px one."""
    resolved = resolve_program_target(target)
    try:
        return shell_item_image(resolved)
    except (OSError, ValueError, ctypes.ArgumentError):
        return legacy_icon_image(resolved)
