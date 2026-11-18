"""Is the PC locked? On Windows the lock screen is the secure desktop, which a normal program cannot open."""
import ctypes


def locked() -> bool:
    """True while the lock screen (the secure desktop) has the input."""
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.OpenInputDesktop.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    user32.OpenInputDesktop.restype = ctypes.c_void_p
    user32.CloseDesktop.argtypes = [ctypes.c_void_p]
    desktop = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
    if not desktop:
        return True
    user32.CloseDesktop(desktop)
    return False
