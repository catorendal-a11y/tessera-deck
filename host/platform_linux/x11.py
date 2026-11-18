"""X11 backend: xdotool for input and windows, xclip for the clipboard. Both are plain command line tools, so the
host needs no extra Python package. A missing tool is reported with the package to install."""
from __future__ import annotations

import re
import shutil
import subprocess
import time

from platform_linux import BackendUnavailable
from platform_linux.base import DesktopBackend

TIMEOUT = 5.0
TYPE_CHUNK = 64  # characters per xdotool call when typing without a pause: the stop request is checked between

# The host's key names (input_common.KEY_NAMES) to the X keysym names xdotool takes.
KEYSYMS = {'ctrl': 'Control_L', 'control': 'Control_L', 'shift': 'Shift_L', 'alt': 'Alt_L',
           'win': 'Super_L', 'meta': 'Super_L', 'enter': 'Return', 'return': 'Return', 'tab': 'Tab',
           'esc': 'Escape', 'escape': 'Escape', 'space': 'space', 'backspace': 'BackSpace', 'delete': 'Delete',
           'home': 'Home', 'end': 'End', 'pageup': 'Prior', 'pagedown': 'Next',
           'left': 'Left', 'up': 'Up', 'right': 'Right', 'down': 'Down',
           'comma': 'comma', 'period': 'period', 'slash': 'slash', 'grave': 'grave',
           'lbracket': 'bracketleft', 'rbracket': 'bracketright', 'minus': 'minus', 'equals': 'equal',
           'semicolon': 'semicolon', 'quote': 'apostrophe', 'backslash': 'backslash',
           'insert': 'Insert', 'printscreen': 'Print', 'apps': 'Menu', 'capslock': 'Caps_Lock',
           'volumemute': 'XF86AudioMute', 'volumedown': 'XF86AudioLowerVolume', 'volumeup': 'XF86AudioRaiseVolume',
           'playpause': 'XF86AudioPlay', 'medianext': 'XF86AudioNext', 'mediaprev': 'XF86AudioPrev',
           'mediastop': 'XF86AudioStop'}
KEYSYMS.update({c: c for c in 'abcdefghijklmnopqrstuvwxyz0123456789'})
KEYSYMS.update({f'numpad{i}': f'KP_{i}' for i in range(10)})
KEYSYMS.update({f'f{i}': f'F{i}' for i in range(1, 25)})

MOUSE_BUTTONS = {'left': '1', 'middle': '2', 'right': '3'}
# xdotool windowstate takes one property per call, and its --toggle does not turn a property off again on every
# window manager: maximize and restore are two calls each, and topmost reads the current state first.
MAXIMIZED = ('MAXIMIZED_VERT', 'MAXIMIZED_HORZ')
HINT = {'xdotool': 'xdotool', 'xclip': 'xclip'}


def run(args: list[str], stdin: str | None = None, timeout: float = TIMEOUT, detach: bool = False) -> str:
    """Run a tool and return its output. Raises BackendUnavailable when the tool is missing, OSError when it fails.

    `detach`: the tool leaves a background process behind (xclip serving the clipboard), which would keep a pipe
    open for good, so its output is not captured."""
    if shutil.which(args[0]) is None:
        raise BackendUnavailable(f'{args[0]} is not installed: install the "{HINT.get(args[0], args[0])}" package')
    try:
        if detach:
            done = subprocess.run(args, input=stdin, text=True, timeout=timeout, check=False,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            done.stdout = done.stderr = ''
        else:
            done = subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise OSError(f'{args[0]} did not answer within {timeout:g} seconds') from exc
    if done.returncode != 0:
        raise OSError(f'{args[0]} failed: {(done.stderr or "").strip()[:200] or done.returncode}')
    return done.stdout


class X11Backend(DesktopBackend):
    name = 'x11'

    def __init__(self, runner=run):
        self.run = runner

    # input
    @staticmethod
    def keysym(name: str) -> str:
        try:
            return KEYSYMS[name]
        except KeyError:
            raise ValueError(f'Unknown key: {name!r}') from None

    def send_keys(self, names):
        symbols = [self.keysym(name) for name in names]
        args = ['xdotool']
        for symbol in symbols:
            args += ['keydown', symbol]
        for symbol in reversed(symbols):  # released even when a later key fails: one call, so nothing stays held
            args += ['keyup', symbol]
        self.run(args)

    def send_text(self, text, pause=0.0, wait=time.sleep):
        chars = text.replace('\r\n', '\n').replace('\r', '\n')
        if pause:
            for n, char in enumerate(chars):
                self.run(['xdotool', 'type', '--clearmodifiers', '--delay', '0', '--', char])
                if n + 1 < len(chars) and wait(pause):
                    break
            return
        for start in range(0, len(chars), TYPE_CHUNK):
            # 12 ms is xdotool's own default and not an arbitrary choice: it types a character that is not on the keyboard by binding
            # it to a spare keycode for a moment, and at 2 ms the receiving program often misses that binding and drops the
            # character (the test failed every time with 2 ms and never with 12 ms).
            self.run(['xdotool', 'type', '--clearmodifiers', '--delay', '12', '--', chars[start:start + TYPE_CHUNK]])
            if start + TYPE_CHUNK < len(chars) and wait(0):
                break

    def send_mouse(self, op, x=0, y=0, amount=0):
        if op in MOUSE_BUTTONS:
            self.run(['xdotool', 'click', MOUSE_BUTTONS[op]])
        elif op == 'double':
            self.run(['xdotool', 'click', '--repeat', '2', '--delay', '50', '1'])
        elif op == 'scroll':
            if amount:
                self.run(['xdotool', 'click', '--repeat', str(abs(amount)), '--delay', '10', '4' if amount > 0 else '5'])
        elif op == 'move':
            self.run(['xdotool', 'mousemove_relative', '--', str(int(x)), str(int(y))])
        elif op == 'moveto':
            self.run(['xdotool', 'mousemove', str(int(x)), str(int(y))])
        else:
            raise ValueError(f'Unknown mouse operation: {op}')

    def set_clipboard(self, text):
        # xclip keeps the text and serves it from a background process until another program takes the clipboard
        self.run(['xclip', '-selection', 'clipboard', '-in'], stdin=text, detach=True)

    # windows
    def active_window(self):
        try:
            window = self.run(['xdotool', 'getactivewindow']).strip()
        except BackendUnavailable:
            raise
        except OSError:
            return None  # no window manager, or nothing has the focus
        if not window.isdigit():
            return None
        try:
            lines = self.run(['xdotool', 'getwindowpid', window, 'getwindowname', window]).splitlines()
        except BackendUnavailable:
            raise
        except OSError:
            return {'id': window, 'pid': 0, 'title': ''}
        pid = int(lines[0]) if lines and lines[0].strip().isdigit() else 0
        return {'id': window, 'pid': pid, 'title': lines[1] if len(lines) > 1 else ''}

    def find_window(self, pids):
        for pid in sorted(pids):
            try:
                found = self.run(['xdotool', 'search', '--onlyvisible', '--pid', str(pid), '--name', '.']).split()
            except BackendUnavailable:
                raise
            except OSError:
                continue  # xdotool search exits 1 when there is no match
            if found:
                return found[0]
        return None

    def window_op(self, window, op):
        target = [window] if window else []
        if op == 'minimize':
            self.run(['xdotool', 'windowminimize', *target] if window else ['xdotool', 'getactivewindow', 'windowminimize'])
        elif op == 'focus':
            if not window:
                return False
            self.run(['xdotool', 'windowactivate', '--sync', window])
        elif op == 'close':
            self.run(['xdotool', 'windowquit', *target] if window else ['xdotool', 'getactivewindow', 'windowquit'])
        elif op == 'maximize':
            self.set_states(window, '--add', MAXIMIZED)
        elif op == 'restore':
            if window:
                self.run(['xdotool', 'windowactivate', '--sync', window])  # also brings a minimized window back
            self.set_states(window, '--remove', MAXIMIZED)
        elif op == 'topmost':
            self.set_states(window, '--remove' if 'ABOVE' in self.states(window) else '--add', ('ABOVE',))
        elif op == 'next_monitor':
            return self.next_monitor(window)
        else:
            raise ValueError(f'Unknown window operation: {op}')
        return True

    def set_states(self, window, flag, names):
        for name in names:
            if window:
                self.run(['xdotool', 'windowstate', flag, name, window])
            else:
                self.run(['xdotool', 'getactivewindow', 'windowstate', flag, name])

    def states(self, window):
        """The _NET_WM_STATE names of the window (without the prefix); empty without xprop."""
        try:
            target = window or self.run(['xdotool', 'getactivewindow']).strip()
            line = self.run(['xprop', '-id', target, '_NET_WM_STATE'])
        except BackendUnavailable:
            return set()
        return set(re.findall(r'_NET_WM_STATE_([A-Z_]+)', line))

    def monitors(self):
        """[(x, y, width, height)] of the monitors, left to right."""
        found = []
        for line in self.run(['xrandr', '--listmonitors']).splitlines()[1:]:
            match = re.search(r'(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)', line)
            if match:
                width, height, x, y = (int(part) for part in match.groups())
                found.append((x, y, width, height))
        return sorted(found)

    def next_monitor(self, window):
        window = window or self.run(['xdotool', 'getactivewindow']).strip()
        geometry = dict(line.split('=') for line in self.run(['xdotool', 'getwindowgeometry', '--shell', window]).split())
        x, y, width, height = (int(geometry[key]) for key in ('X', 'Y', 'WIDTH', 'HEIGHT'))
        screens = self.monitors()
        if len(screens) < 2:
            return True
        centre = (x + width // 2, y + height // 2)
        here = next((n for n, (sx, sy, sw, sh) in enumerate(screens)
                     if sx <= centre[0] < sx + sw and sy <= centre[1] < sy + sh), 0)
        sx, sy, _, _ = screens[here]
        nx, ny, nw, nh = screens[(here + 1) % len(screens)]
        goal = (nx + min(max(x - sx, 0), max(nw - width, 0)), ny + min(max(y - sy, 0), max(nh - height, 0)))
        self.run(['xdotool', 'windowmove', window, str(goal[0]), str(goal[1])])
        # windowmove places the frame, getwindowgeometry reports the content: the difference is the title bar, and
        # without this correction every move would push the window down by that much
        geometry = dict(line.split('=') for line in self.run(['xdotool', 'getwindowgeometry', '--shell', window]).split())
        off = (int(geometry['X']) - goal[0], int(geometry['Y']) - goal[1])
        if off != (0, 0):
            self.run(['xdotool', 'windowmove', window, str(goal[0] - off[0]), str(goal[1] - off[1])])
        return True
