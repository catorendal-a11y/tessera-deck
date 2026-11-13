"""Windows input and focus: synthetic keys and mouse, the foreground window and bringing a program to the front."""
import ctypes
import os
import time

import psutil

IS_WINDOWS = os.name == 'nt'
VK = {'ctrl': 0x11, 'control': 0x11, 'shift': 0x10, 'alt': 0x12,
      'win': 0x5b, 'meta': 0x5b, 'enter': 13, 'return': 13, 'tab': 9,
      'esc': 27, 'escape': 27, 'space': 32, 'backspace': 8, 'delete': 46,
      'home': 36, 'end': 35, 'pageup': 33, 'pagedown': 34,
      'left': 37, 'up': 38, 'right': 39, 'down': 40,
      'comma': 0xbc, 'period': 0xbe, 'slash': 0xbf, 'grave': 0xc0,
      'lbracket': 0xdb, 'rbracket': 0xdd, 'minus': 0xbd, 'equals': 0xbb,
      'semicolon': 0xba, 'quote': 0xde, 'backslash': 0xdc,
      'insert': 45, 'printscreen': 44, 'apps': 0x5d, 'capslock': 20,
      'volumemute': 0xad, 'volumedown': 0xae, 'volumeup': 0xaf,
      'playpause': 0xb3, 'medianext': 0xb0, 'mediaprev': 0xb1, 'mediastop': 0xb2}
VK.update({c: ord(c.upper()) for c in 'abcdefghijklmnopqrstuvwxyz0123456789'})
VK.update({f'numpad{i}': 0x60 + i for i in range(10)})
VK.update({f'f{i}': 0x6f + i for i in range(1, 25)})
# Navigation keys must carry KEYEVENTF_EXTENDEDKEY or some apps read them as numpad keys.
EXTENDED_VK = frozenset({33, 34, 35, 36, 37, 38, 39, 40, 44, 45, 46, 0x5b, 0x5d})
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 1, 2


def parse_hotkey(combo):
    parts = [p.strip().lower() for p in combo.split('+')]
    if not parts or any(p not in VK for p in parts):
        raise ValueError(f'Unknown hotkey: {combo!r}')
    return [VK[p] for p in parts]


def dry_hotkey(combo):
    try:
        parse_hotkey(combo)
        return True, combo.split('+')
    except ValueError:
        return False, combo.split('+')


if IS_WINDOWS:
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
                    ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                    ('dwExtraInfo', ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                    ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                    ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]

    class INPUTUNION(ctypes.Union):
        _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ('u',)
        _fields_ = [('type', wintypes.DWORD), ('u', INPUTUNION)]

    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                  wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _key(vk=0, scan=0, flags=0):
    if not IS_WINDOWS:
        raise OSError('Hotkeys and typing need Windows')
    value = INPUT(type=1)
    value.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    if user32.SendInput(1, ctypes.byref(value), ctypes.sizeof(value)) != 1:
        raise OSError('Windows refused the key press (check the permissions of Tessera)')


MOUSE_FLAGS = {'left': (0x2, 0x4), 'right': (0x8, 0x10), 'middle': (0x20, 0x40)}
MOUSE_OPERATIONS = ('left', 'right', 'middle', 'double', 'scroll', 'move', 'moveto')


def _mouse(flags, dx=0, dy=0, data=0):
    if not IS_WINDOWS:
        raise OSError('Mouse actions need Windows')
    value = INPUT(type=0)
    value.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
    if user32.SendInput(1, ctypes.byref(value), ctypes.sizeof(value)) != 1:
        raise OSError('Windows refused the mouse input (check the permissions of Tessera)')


def send_mouse(op, x=0, y=0, amount=0, press=None):
    # click: left, right, middle, double; scroll: `amount` notches (positive up); move: relative pixels;
    # moveto: absolute screen position in pixels.
    press = press or _mouse
    if op in MOUSE_FLAGS or op == 'double':
        down, up = MOUSE_FLAGS['left' if op == 'double' else op]
        for _ in range(2 if op == 'double' else 1):
            press(down)
            press(up)
    elif op == 'scroll':
        press(0x800, data=amount * 120)
    elif op == 'move':
        press(0x1, x, y)
    elif op == 'moveto':
        # with the virtual-desk flag 0..65535 spans every monitor, so scale with the virtual screen, not the primary one
        left, top, width, height = (user32.GetSystemMetrics(index) for index in (76, 77, 78, 79))
        press(0x8001 | 0x4000, round((x - left) * 65535 / max(1, width - 1)), round((y - top) * 65535 / max(1, height - 1)))
    else:
        raise ValueError(f'Unknown mouse operation: {op}')


def _extended_flag(vk):
    return KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VK else 0


def send_hotkey(combo):
    pressed = []
    try:
        for vk in parse_hotkey(combo):
            _key(vk=vk, flags=_extended_flag(vk))
            pressed.append(vk)
    finally:
        for vk in reversed(pressed):
            _key(vk=vk, flags=KEYEVENTF_KEYUP | _extended_flag(vk))


def send_text(text, pause=0.0, wait=time.sleep):
    # `pause` seconds between characters makes the typing look and behave like a person typing.
    raw = text.encode('utf-16-le')
    for i in range(0, len(raw), 2):
        code = int.from_bytes(raw[i:i+2], 'little')
        _key(scan=code, flags=4)
        _key(scan=code, flags=6)
        if pause and i + 2 < len(raw):
            wait(pause)


FRAME_HOST = 'applicationframehost.exe'
# Windows surfaces that take focus for a moment (search, Start, notifications, Alt+Tab, the lock screen): they say
# nothing about which program you are working in, so they never end or start an automatic profile switch.
NEUTRAL_EXES = frozenset({'searchhost.exe', 'searchapp.exe', 'startmenuexperiencehost.exe', 'shellexperiencehost.exe',
                          'textinputhost.exe', 'lockapp.exe', 'shellhost.exe'})
NEUTRAL_EXPLORER_TITLES = frozenset({'', 'task switching', 'task view'})
TESSERA_WINDOW_EXES = frozenset({'python.exe', 'pythonw.exe', 'msedgewebview2.exe'})


def is_neutral_window(context):
    exe, title = context.get('exe', ''), context.get('title', '')
    if exe in NEUTRAL_EXES:
        return True
    if exe == 'explorer.exe':
        return title in NEUTRAL_EXPLORER_TITLES
    return exe in TESSERA_WINDOW_EXES and title.startswith('tessera')


def real_app_exe(exe, child_exes):
    """Store (UWP) apps are drawn inside ApplicationFrameHost; the program behind the frame is the app that matters."""
    if exe != FRAME_HOST:
        return exe
    return next((name for name in child_exes if name and name != FRAME_HOST), exe)


def child_process_names(hwnd):
    names = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(child, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(child, ctypes.byref(owner))
        try:
            names.append(psutil.Process(owner.value).name().lower())
        except (psutil.Error, OSError):
            pass
        return True

    user32.EnumChildWindows(hwnd, visit, 0)
    return names


def foreground_context():
    if not IS_WINDOWS:
        return {'exe': '', 'title': '', 'processes': []}
    hwnd = user32.GetForegroundWindow()
    return window_context(hwnd) if hwnd else {'exe': '', 'title': '', 'processes': []}


def window_context(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    length = min(max(user32.GetWindowTextLengthW(hwnd), 0), 4096)
    title_buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
    title = title_buffer.value.lower()
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return {'exe': '', 'title': title, 'processes': []}
    exe = ''
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            exe = os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(handle)
    if exe == FRAME_HOST:
        exe = real_app_exe(exe, child_process_names(hwnd))
    processes = [exe] if exe else []
    processes += [name for name in child_names(pid.value) if name not in processes]
    return {'exe': exe, 'title': title, 'processes': processes}


CHILD_NAMES_SECONDS = 3.0  # listing children walks every process on the PC; a new foreground window is listed at once
_child_names = (None, 0.0, [])


def child_names(pid):
    global _child_names
    known, listed_at, names = _child_names
    now = time.monotonic()
    if known == pid and now - listed_at < CHILD_NAMES_SECONDS:
        return names
    names = []
    try:
        for child in psutil.Process(pid).children(recursive=True):
            name = child.name().lower()
            if name and name not in names:
                names.append(name)
    except (psutil.Error, OSError):
        pass
    _child_names = (pid, now, names)
    return names


def bring_to_front(user32, hwnd):
    """Show a window in front. Only a minimized window is restored: SW_RESTORE on a maximized one would shrink it."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    if user32.GetForegroundWindow() == hwnd:
        return
    # Windows refuses a background program the foreground and flashes the taskbar button instead. A key press on
    # the panel is the user's own request, so borrow the right from the thread that owns the window in front.
    front = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    mine = kernel32.GetCurrentThreadId() if IS_WINDOWS else 0
    attached = bool(front) and front != mine and bool(user32.AttachThreadInput(mine, front, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(mine, front, False)
    if user32.GetForegroundWindow() != hwnd:  # last resort: a tap on Alt counts as the user's input
        user32.keybd_event(0x12, 0, 0, 0)
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(0x12, 0, 2, 0)


def focus_existing_process(process_name):
    """Restore the first visible window owned by process_name."""
    if not IS_WINDOWS or not process_name:
        return False
    wanted = process_name.lower()
    pids = set()
    try:
        for process in psutil.process_iter(['pid', 'name']):
            if (process.info.get('name') or '').lower() == wanted:
                pids.add(process.info['pid'])
    except (psutil.Error, OSError):
        return False
    if not pids:
        return False
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in pids and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(visit, 0)
    if not found:
        return False
    bring_to_front(user32, found[0])
    return True


def matches_foreground(pattern, context):
    """Match a foreground executable, terminal child process, or window title."""
    pattern = pattern.strip().lower()
    if pattern.startswith('title:'):
        return pattern.removeprefix('title:').strip() in context.get('title', '').lower()
    if pattern.startswith('process:'):
        pattern = pattern.removeprefix('process:').strip()
    return pattern in {name.lower() for name in context.get('processes', [])}
