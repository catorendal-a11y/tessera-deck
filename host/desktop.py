"""The input and window functions of the system the host runs on.

platform_windows/input.py. The rest of the host imports these names from here. The key names, the operation lists
and the rest of the shared vocabulary are in input_common.
"""
from platform_support import load

_input = load('input')
bring_to_front, focus_existing_process, foreground_context = _input.bring_to_front, _input.focus_existing_process, _input.foreground_context  # noqa: F401, E501
is_neutral_window, matches_foreground, process_window = _input.is_neutral_window, _input.matches_foreground, _input.process_window  # noqa: F401, E501
send_hotkey, send_mouse, send_text = _input.send_hotkey, _input.send_mouse, _input.send_text  # noqa: F401
set_clipboard, window_action = _input.set_clipboard, _input.window_action  # noqa: F401


def open_path(path) -> None:
    """Open a file or folder with the program the system has for it (Windows: os.startfile)."""
    load('processes').open_path(path)


def open_target(target: str) -> None:
    """Open a file, folder, address or program the way an `open` action does."""
    load('processes').open_target(target)


def script_command(script: str):
    """The command that runs a script file: Windows picks by extension (py launcher, cmd, AutoHotkey ...)."""
    return load('programs').script_command(script)


def locate(target: str):
    """Where a program that moved is now (Windows: App Paths, the Program Files folders); None when not found."""
    return load('programs').locate(target)
