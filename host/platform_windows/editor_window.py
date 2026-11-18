"""The editor's own window on Windows: a WebView2 window with the taskbar identity, the work-area fit and raising an
editor that is already open."""
import logging
import os

APP_USER_MODEL_ID = 'Tessera.Editor'


def activate_window(pid):
    """Restore the existing native editor instead of opening a duplicate."""
    if os.name != 'nt':
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        found = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def visit(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                title = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title, length + 1)
                if title.value == 'Tessera':
                    found.append(hwnd)
                    return False
            return True

        user32.EnumWindows(visit, 0)
        if not found:
            return False
        from platform_windows.input import bring_to_front
        bring_to_front(user32, found[0])
        return True
    except (AttributeError, OSError, ValueError):
        return False


def brand_taskbar_identity():
    """Give this process its own Windows identity.

    Without one, Windows groups the editor window under pythonw.exe and shows the Python
    file icon on the taskbar instead of the window's own icon.
    """
    if os.name != 'nt':
        return
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def fit_to_work_area(window):
    """Fill the screen without covering the taskbar: a maximized WebView2 window can end up under it."""
    try:
        import ctypes
        from ctypes import wintypes
        window.events.shown.wait(15)
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        area = wintypes.RECT()
        if not user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0):  # SPI_GETWORKAREA: the screen minus the taskbar
            return
        handle = user32.FindWindowW(None, 'Tessera')
        if handle:
            user32.ShowWindow(handle, 9)  # SW_RESTORE, so the size below applies
            user32.SetWindowPos(handle, 0, area.left, area.top, area.right - area.left, area.bottom - area.top, 0x0044)  # no z-order change, show
    except (AttributeError, OSError, ValueError):
        pass


def open_native_window(url, geometry_of, save_geometry, min_window, root):
    """Open the editor in a native WebView2 window. True when the window was shown and closed; False on any failure
    (the caller then opens a browser). `geometry_of(screen)` and `save_geometry(dict)` remember the last size and place."""
    brand_taskbar_identity()
    try:
        import webview
        webview.settings['ALLOW_DOWNLOADS'] = True  # Export saves through a download; pywebview cancels them all without this
        screen = webview.screens[0]
        width, height, x, y = geometry_of(screen)
        window = webview.create_window('Tessera', url, width=width, height=height, x=x, y=y,
                                       min_size=(min(min_window[0], screen.width), min(min_window[1], screen.height)),
                                       background_color='#0A0E10', text_select=True)
        # Remember the last size and place: the events give logical pixels, the same units create_window takes.
        geometry = {}
        window.events.resized += lambda width, height: geometry.update(width=width, height=height)
        window.events.moved += lambda x, y: geometry.update(x=x, y=y)
        window.events.closing += lambda: save_geometry(dict(geometry))
        webview.start(fit_to_work_area if x is None else None, (window,), private_mode=True,
                      storage_path=str(root / 'host/.webview-data'), icon=str(root / 'host/tessera.ico'))
        return True
    except Exception:
        logging.getLogger(__name__).warning('WebView2 window failed; using the browser', exc_info=True)
    return False
