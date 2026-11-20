"""The input and window functions of the system the host runs on.

Windows: platform_windows/input.py. Linux: platform_linux, which picks the backend of the desktop session (X11 today;
Wayland has a place in platform_linux/wayland.py). The rest of the host imports these names from here. The key names, the
operation lists and the rest of the shared vocabulary are in input_common.
"""
from platform_support import IS_LINUX, load

if IS_LINUX:
    from platform_linux.input import (bring_to_front, focus_existing_process, foreground_context,  # noqa: F401
                                      is_neutral_window, matches_foreground, process_window, send_hotkey, send_mouse,
                                      send_text, set_clipboard, window_action)
else:
    from platform_windows.input import (bring_to_front, focus_existing_process, foreground_context,  # noqa: F401
                                        is_neutral_window, matches_foreground, process_window, send_hotkey, send_mouse,
                                        send_text, set_clipboard, window_action)


def open_path(path) -> None:
    """Open a file or folder with the program the system has for it (Windows: os.startfile; Linux: xdg-open)."""
    load('processes').open_path(path)


def open_target(target: str) -> None:
    """Open a file, folder, address or program the way an `open` action does."""
    load('processes').open_target(target)


def script_command(script: str):
    """The command that runs a script file: Windows picks by extension (py launcher, cmd, AutoHotkey ...), Linux
    uses the interpreters it has (python3, bash, node, pwsh)."""
    return load('programs').script_command(script)


def locate(target: str):
    """Where a program that moved is now (Windows: App Paths, the Program Files folders); None when not found."""
    return load('programs').locate(target)
