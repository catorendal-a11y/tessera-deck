"""Tray icon set-up on Linux (platform_windows/tray.py is the Windows counterpart)."""


def prepare(icon, separator) -> None:
    """Notices go to the desktop's notifications (notify-send), whichever tray backend pystray picked. pystray's
    legacy X11 tray has no right-click menu of its own, so one is added; it is the backend on X11, and also on a
    Wayland desktop through XWayland (Plasma shows it with xembedsniproxy). An icon with a menu is left alone."""
    from platform_linux.notify import notify
    from platform_linux import x11_tray_menu
    icon.notify = lambda message, title=None: notify(message, title or 'Tessera')
    x11_tray_menu.attach(icon, separator)
