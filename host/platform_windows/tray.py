"""Tray icon set-up on Windows: pystray's own balloons and menu work as they are (platform_linux/tray.py is the Linux
counterpart)."""


def choose_backend() -> str:
    return 'default'


def prepare(icon, separator) -> None:
    return None
