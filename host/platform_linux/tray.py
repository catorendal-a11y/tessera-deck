"""Tray icon set-up on Linux (platform_windows/tray.py is the Windows counterpart)."""


def prepare(icon, separator) -> None:
    """The X11 tray cannot show balloons, so notices go to the desktop's notifications, and it has no menu of its own."""
    from platform_linux import tray_menu
    from platform_linux.notify import notify
    icon.notify = lambda message, title=None: notify(message, title or 'Tessera')
    tray_menu.attach(icon, separator)
