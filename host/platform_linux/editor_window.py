"""The editor's window on Linux. The editor is a browser tab here, so there is no native window to raise or brand (the
Windows counterpart is platform_windows/editor_window.py with the same functions)."""


def activate_window(pid):
    return False


def brand_taskbar_identity():
    return None


def open_native_window(url, geometry_of, save_geometry, min_window, root):
    """False: the caller opens the browser."""
    return False
