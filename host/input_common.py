"""What every system shares about input and focus: the key names, the operation lists, and matching a program.

The key names are the vocabulary of profiles ("ctrl+shift+t", "volumeup"). Each system turns them into its own codes
(platform_windows/input.py: Windows virtual-key codes; platform_linux/x11.py: X keysyms). Nothing here touches the system.
"""
import time

import psutil

from platform_support import IS_WINDOWS  # noqa: F401  (the host's modules import it from here)

KEY_NAMES = ('ctrl', 'control', 'shift', 'alt', 'win', 'meta', 'enter', 'return',
             'tab', 'esc', 'escape', 'space', 'backspace', 'delete', 'home', 'end',
             'pageup', 'pagedown', 'left', 'up', 'right', 'down', 'comma', 'period',
             'slash', 'grave', 'lbracket', 'rbracket', 'minus', 'equals', 'semicolon', 'quote',
             'backslash', 'insert', 'printscreen', 'apps', 'capslock', 'volumemute', 'volumedown', 'volumeup',
             'playpause', 'medianext', 'mediaprev', 'mediastop', 'a', 'b', 'c', 'd',
             'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l',
             'm', 'n', 'o', 'p', 'q', 'r', 's', 't',
             'u', 'v', 'w', 'x', 'y', 'z', '0', '1',
             '2', '3', '4', '5', '6', '7', '8', '9',
             'numpad0', 'numpad1', 'numpad2', 'numpad3', 'numpad4', 'numpad5', 'numpad6', 'numpad7',
             'numpad8', 'numpad9', 'f1', 'f2', 'f3', 'f4', 'f5', 'f6',
             'f7', 'f8', 'f9', 'f10', 'f11', 'f12', 'f13', 'f14',
             'f15', 'f16', 'f17', 'f18', 'f19', 'f20', 'f21', 'f22',
             'f23', 'f24')
MOUSE_OPERATIONS = ('left', 'right', 'middle', 'double', 'scroll', 'move', 'moveto')
WINDOW_OPERATIONS = ('minimize', 'maximize', 'restore', 'close', 'topmost', 'next_monitor', 'focus')


def split_hotkey(combo):
    """The key names of a hotkey such as "ctrl+c", lowercase; ValueError when one is not in the vocabulary."""
    parts = [p.strip().lower() for p in combo.split('+')]
    if not parts or any(p not in KEY_NAMES for p in parts):
        raise ValueError(f'Unknown hotkey: {combo!r}')
    return parts


def dry_hotkey(combo):
    try:
        split_hotkey(combo)
        return True, combo.split('+')
    except ValueError:
        return False, combo.split('+')


CHILD_NAMES_SECONDS = 3.0  # listing children walks every process on the PC; a new foreground window is listed at once
_child_names = (None, 0.0, [])


def child_names(pid):
    global _child_names
    known, listed_at, names = _child_names
    now = time.monotonic()
    if known == pid and now - listed_at < CHILD_NAMES_SECONDS:
        return names
    names = []
    try:
        for child in psutil.Process(pid).children(recursive=True):
            name = child.name().lower()
            if name and name not in names:
                names.append(name)
    except (psutil.Error, OSError):
        pass
    _child_names = (pid, now, names)
    return names


def matches_foreground(pattern, context):
    """Match a foreground executable, terminal child process, or window title."""
    pattern = pattern.strip().lower()
    if pattern.startswith('title:'):
        wanted = pattern.removeprefix('title:').strip()
        return bool(wanted) and wanted in context.get('title', '').lower()  # '' is in every title
    if pattern.startswith('process:'):
        pattern = pattern.removeprefix('process:').strip()
    return pattern in {name.lower() for name in context.get('processes', [])}
