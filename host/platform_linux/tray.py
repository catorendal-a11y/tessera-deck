"""Tray icon set-up on Linux (platform_windows/tray.py is the Windows counterpart)."""


def prepare(icon, separator) -> None:
    """Notices go to the desktop's notifications (notify-send), whichever tray backend pystray picked. Only an X11
    session adds the right-click menu: the legacy X11 tray has none of its own. A Wayland session gets its tray from
    StatusNotifier, which draws the icon's own menu."""
    from platform_linux import session_type
    from platform_linux.notify import notify
    icon.notify = lambda message, title=None: notify(message, title or 'Tessera')
    if session_type() == 'x11':
        from platform_linux import x11_tray_menu
        x11_tray_menu.attach(icon, separator)
