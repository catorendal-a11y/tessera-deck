"""The desktop's program list and shortcuts for the editor (the Windows counterpart is platform_windows/shell.py)."""
from platform_linux import programs


def scan_programs():
    """The .desktop entries of the application menu."""
    return programs.scan()


def shortcut_target(path):
    """Linux has no .lnk shortcuts: the path is its own target."""
    return str(path)
