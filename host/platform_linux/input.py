"""The input and window functions for Linux, on top of the session's desktop backend.

`desktop.py` gives the rest of the host these functions on Linux and the ones of platform_windows/input.py on Windows, so
the host does not know which system it runs on.

Process names are the lowercase executable names (`firefox`); a trailing `.exe` in a profile or an action is ignored,
so a profile written on Windows still matches the same program here.
"""
from __future__ import annotations

import os
import time

import psutil

from platform_linux import backend

# Desktop shells and lock screens take the focus for a moment and say nothing about the program you work in.
NEUTRAL_EXES = frozenset({'cinnamon', 'cinnamon-screensaver', 'cinnamon-launcher', 'cinnamon-session', 'gnome-shell',
                          'plasmashell', 'krunner', 'xfdesktop', 'xfce4-panel', 'nemo-desktop', 'budgie-panel',
                          'lxpanel', 'polybar', 'i3bar', 'xscreensaver', 'light-locker', 'i3lock', 'ulauncher'})


def plain_name(name: str) -> str:
    name = name.strip().lower()
    return name[:-4] if name.endswith('.exe') else name


def parse_names(combo: str) -> list[str]:
    from input_common import split_hotkey
    return split_hotkey(combo)  # one vocabulary: an unknown key is refused the same way on every system


def send_hotkey(combo):
    backend().send_keys(parse_names(combo))


def send_text(text, pause=0.0, wait=time.sleep):
    backend().send_text(text, pause, wait)


def send_mouse(op, x=0, y=0, amount=0, press=None):
    backend().send_mouse(op, x, y, amount)


def set_clipboard(text, tries=10, wait=time.sleep):
    backend().set_clipboard(text)


def process_name(pid: int) -> str:
    try:
        process = psutil.Process(pid)
        # comm is cut to 15 characters; the executable's file name is whole
        name = os.path.basename(process.exe()) or process.name()
    except (psutil.Error, OSError):
        try:
            name = psutil.Process(pid).name()
        except (psutil.Error, OSError):
            return ''
    return plain_name(name)


def window_context(window: dict) -> dict:
    from input_common import child_names
    exe = process_name(window['pid']) if window.get('pid') else ''
    processes = [exe] if exe else []
    if window.get('pid'):
        processes += [name for name in child_names(window['pid']) if name not in processes]
    return {'exe': exe, 'title': window.get('title', '').lower(), 'processes': [plain_name(n) for n in processes]}


def foreground_context():
    window = backend().active_window()
    return window_context(window) if window else {'exe': '', 'title': '', 'processes': []}


def is_neutral_window(context):
    exe, title = context.get('exe', ''), context.get('title', '')
    if exe in NEUTRAL_EXES:
        return True
    return exe.startswith('python') and title.startswith('tessera')


def matches_foreground(pattern, context):
    """Match a foreground executable, terminal child process, or window title."""
    pattern = pattern.strip().lower()
    if pattern.startswith('title:'):
        return pattern.removeprefix('title:').strip() in context.get('title', '').lower()
    if pattern.startswith('process:'):
        pattern = pattern.removeprefix('process:').strip()
    return plain_name(pattern) in {plain_name(name) for name in context.get('processes', [])}


def process_window(process_name_):
    """The first visible, titled window owned by the process, or None."""
    wanted = plain_name(process_name_ or '')
    if not wanted:
        return None
    pids = set()
    try:
        for process in psutil.process_iter(['pid', 'name', 'exe']):
            names = {plain_name(process.info.get('name') or ''), plain_name(os.path.basename(process.info.get('exe') or ''))}
            if wanted in names:
                pids.add(process.info['pid'])
    except (psutil.Error, OSError):
        return None
    return backend().find_window(pids) if pids else None


def focus_existing_process(process_name_):
    window = process_window(process_name_)
    return bool(window) and backend().window_op(window, 'focus')


def bring_to_front(_unused, window):
    backend().window_op(window, 'focus')


def window_action(op, process=''):
    """Do `op` to the first window of `process`, or to the window in front. Returns False when there is none."""
    from input_common import WINDOW_OPERATIONS
    if op not in WINDOW_OPERATIONS:
        raise ValueError(f'Unknown window operation: {op}')
    if process:
        window = process_window(process)
        return bool(window) and backend().window_op(window, op)
    if backend().active_window() is None:
        return False
    return backend().window_op(None, op)
