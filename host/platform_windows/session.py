"""Is the PC locked, and for how long has nobody used it? On Windows the lock screen is the secure desktop, which a normal program cannot open."""
import ctypes


def locked() -> bool:
    """True while the lock screen (the secure desktop) has the input."""
    import os
    if os.name != 'nt':
        return False
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.OpenInputDesktop.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    user32.OpenInputDesktop.restype = ctypes.c_void_p
    user32.CloseDesktop.argtypes = [ctypes.c_void_p]
    desktop = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
    if not desktop:
        return True
    user32.CloseDesktop(desktop)
    return False


def idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input on this PC; infinity where Windows cannot tell."""
    import os
    if os.name != 'nt':
        return float('inf')

    class LastInputInfo(ctypes.Structure):
        _fields_ = [('cbSize', ctypes.c_uint32), ('dwTime', ctypes.c_uint32)]

    info = LastInputInfo(ctypes.sizeof(LastInputInfo), 0)
    if not ctypes.WinDLL('user32').GetLastInputInfo(ctypes.byref(info)):
        return float('inf')
    kernel32 = ctypes.WinDLL('kernel32')
    kernel32.GetTickCount.restype = ctypes.c_uint32
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000  # both wrap after 49.7 days
