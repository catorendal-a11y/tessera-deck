"""Wayland backend: ydotool (else the RemoteDesktop portal) for input, kdotool (KDE Plasma) or the Tessera extension
(GNOME Shell) for windows, wl-copy or Klipper for the clipboard.

Wayland has no portable way for a program to send keys, find the window in front or move windows, so each part uses
the tool that works there:

- **Input** goes through `ydotool`, which types on a virtual uinput keyboard and mouse; its daemon `ydotoold` must run
  (`systemctl --user enable --now ydotool`). The device sends key positions, so text is turned into keys with the
  session's own layout (xkb.py): "@" is AltGr+2 on a Norwegian keyboard and Shift+2 on a US one. Caps Lock is read
  from the keyboard's LED, so text comes out in the case it was written in; with no LED to read it is taken as off.
  Where `ydotool` is not installed, input goes through the desktop's RemoteDesktop portal instead (portal.py): the
  desktop asks once, and keys are sent as keysyms, so the layout does not matter and any character can be typed. The
  portal has no absolute pointer position.
- **Windows** (the window in front for smart profiles, focus, minimize, ...) go through `kdotool`, which asks KWin.
  A compositor without such a tool gets a separate part (`windows`), filled by the compositor's own extension: GNOME
  Shell has one (gnome_windows.py, the extension is in host/linux/gnome-extension). Other compositors have neither yet:
  there the window functions say so, and keys and typing still work.
- **The clipboard** uses `wl-copy` (the "wl-clipboard" package), else Plasma's Klipper.
"""
from __future__ import annotations

import glob
import os
import shutil
import time

from platform_linux import BackendUnavailable
from platform_linux.base import DesktopBackend
from platform_linux.keysyms import char_keysym, keysym_number
from platform_linux.portal import BUTTONS, RemoteDesktop
from platform_linux.x11 import run

WINDOWS_MESSAGE = ('Window actions on Wayland need KDE Plasma and kdotool, or GNOME and the Tessera extension for GNOME '
                   'Shell. Keys and typing work without them; log in with an X11 session for window actions on other '
                   'desktops.')
TYPE_CHUNK = 32  # characters per ydotool call: the stop request is checked between
KEY_DELAY_MS = '6'  # between key events; KWin drops keys sent with no gap at all
KEYMAP_SECONDS = 5.0  # the session's layouts are read again after this long; which one is in use is asked every time
PORTAL_TYPE_CHUNK = 64  # characters between two looks at the stop request when typing through the portal
PORTAL_KEY_GAP = 0.004  # seconds between two characters typed through the portal: the compositor takes each event in turn
CAPS_LOCK_LEDS = '/sys/class/leds/*::capslock/brightness'  # the compositor lights the LED of every keyboard

# The host's key names (input_common.KEY_NAMES) to Linux input key codes (linux/input-event-codes.h).
KEYCODES = {'ctrl': 29, 'control': 29, 'shift': 42, 'alt': 56, 'win': 125, 'meta': 125, 'enter': 28, 'return': 28,
            'tab': 15, 'esc': 1, 'escape': 1, 'space': 57, 'backspace': 14, 'delete': 111, 'home': 102, 'end': 107,
            'pageup': 104, 'pagedown': 109, 'left': 105, 'up': 103, 'right': 106, 'down': 108,
            'comma': 51, 'period': 52, 'slash': 53, 'grave': 41, 'lbracket': 26, 'rbracket': 27, 'minus': 12,
            'equals': 13, 'semicolon': 39, 'quote': 40, 'backslash': 43, 'insert': 110, 'printscreen': 99,
            'apps': 127, 'capslock': 58, 'volumemute': 113, 'volumedown': 114, 'volumeup': 115, 'playpause': 164,
            'medianext': 163, 'mediaprev': 165, 'mediastop': 166}
KEYCODES.update(zip('qwertyuiop', range(16, 26), strict=True))
KEYCODES.update(zip('asdfghjkl', range(30, 39), strict=True))
KEYCODES.update(zip('zxcvbnm', range(44, 51), strict=True))
KEYCODES.update(zip('1234567890', range(2, 12), strict=True))
KEYCODES.update(zip((f'numpad{i}' for i in (7, 8, 9, 4, 5, 6, 1, 2, 3, 0)), (71, 72, 73, 75, 76, 77, 79, 80, 81, 82), strict=True))
KEYCODES.update({f'f{i}': 58 + i for i in range(1, 11)})
KEYCODES.update({'f11': 87, 'f12': 88})
KEYCODES.update({f'f{i}': 170 + i for i in range(13, 25)})
# Punctuation and letters in a hotkey mean the character: on a Norwegian keyboard ctrl+minus is the key that types "-", not the
# key in the US minus position, and ctrl+slash is Ctrl+Shift+7, which is how "/" is typed there. The US position is
# the fallback for a character the layout has no single key for (a dead key, or none).
PUNCTUATION = {'comma': ',', 'period': '.', 'slash': '/', 'grave': '`', 'lbracket': '[', 'rbracket': ']',
               'minus': '-', 'equals': '=', 'semicolon': ';', 'quote': "'", 'backslash': '\\'}
SHIFT_CODE, ALTGR_CODE, ENTER_CODE, TAB_CODE = 42, 100, 28, 15
MOUSE_BUTTONS = {'left': '0xC0', 'right': '0xC1', 'middle': '0xC2'}  # 0xC0: press and release


def caps_lock_on(leds: str = CAPS_LOCK_LEDS) -> bool | None:
    """Whether Caps Lock is on; None when no keyboard has a Caps Lock LED that can be read, so nothing tells.
    A session has one lock state for all keyboards, ydotool's included."""
    known = None
    for path in glob.glob(leds):
        try:
            with open(path, encoding='ascii') as led:
                if int(led.read().strip() or 0):
                    return True
            known = False
        except (OSError, ValueError):
            continue
    return known


def is_plasma(environ=None) -> bool:
    environ = os.environ if environ is None else environ
    return 'KDE' in environ.get('XDG_CURRENT_DESKTOP', '').upper().split(':') and shutil.which('kdotool') is not None


def desktop_windows(environ=None):
    """The window part of a desktop kdotool does not cover: GNOME has the Tessera extension; no other desktop has one
    yet (None)."""
    environ = os.environ if environ is None else environ
    if 'GNOME' in environ.get('XDG_CURRENT_DESKTOP', '').upper().split(':'):
        from platform_linux.gnome_windows import GnomeWindows
        return GnomeWindows()
    return None


def ydotool_ready(environ=None) -> bool:
    """ydotool is installed and its daemon is up. The client talks to the daemon over a socket it looks for in
    $YDOTOOL_SOCKET, else $XDG_RUNTIME_DIR/.ydotool_socket, else /tmp/.ydotool_socket (ydotool 1.0). ydotool 0.1.x has no
    daemon and no socket, and its commands are different, so it is not used either."""
    environ = os.environ if environ is None else environ
    if shutil.which('ydotool') is None:
        return False
    if environ.get('YDOTOOL_SOCKET'):
        socket = environ['YDOTOOL_SOCKET']
    elif environ.get('XDG_RUNTIME_DIR'):
        socket = environ['XDG_RUNTIME_DIR'] + '/.ydotool_socket'
    else:
        socket = '/tmp/.ydotool_socket'
    return os.path.exists(socket)


def session_backend(environ=None) -> WaylandBackend:
    """The backend of this session: ydotool for input where it is installed and its daemon runs, else the RemoteDesktop
    portal; the window part of the desktop."""
    return WaylandBackend(remote=None if ydotool_ready(environ) else RemoteDesktop(), windows=desktop_windows(environ))


class WaylandBackend(DesktopBackend):
    name = 'wayland'

    def __init__(self, runner=run, keymap=None, plasma=None, caps_lock=caps_lock_on, remote=None, sleep=time.sleep,
                 windows=None):
        self.run = runner
        self.remote = remote  # a RemoteDesktop portal session: input goes through it instead of ydotool
        self.windows = windows  # active_window, find_window and window_op of a desktop without kdotool (GNOME)
        self.sleep = sleep
        self._fixed_keymap = keymap  # a test's layout; None reads the session's
        self._keymaps, self._keymaps_at = {}, 0.0
        self.caps_lock = caps_lock
        self.plasma = is_plasma() if plasma is None else plasma

    # input
    def keymap(self):
        """The keymap of the layout in use right now. Which layout that is, is asked every time: a switch changes what
        every key types, and Plasma can switch with the window in front. The layouts themselves are kept for
        KEYMAP_SECONDS."""
        if self._fixed_keymap is not None:
            return self._fixed_keymap
        from platform_linux import xkb
        now = time.monotonic()
        if now - self._keymaps_at > KEYMAP_SECONDS:
            self._keymaps, self._keymaps_at = {}, now
        group = xkb.active_group()
        if group not in self._keymaps:
            self._keymaps[group] = xkb.session_keymap(group=group)
        return self._keymaps[group]

    def key_strokes(self, names) -> list[tuple[int, bool, bool]]:
        """(key code, shift, altgr) of every key name of a hotkey; ValueError for a name that is no key."""
        keymap, strokes = None, []
        for name in names:
            if name not in KEYCODES:
                raise ValueError(f'Unknown key: {name!r}')
            found = None
            letter = len(name) == 1 and name.isalpha()
            if name in PUNCTUATION or letter:
                try:
                    keymap = keymap or self.keymap()
                    found = keymap.strokes(PUNCTUATION.get(name, name))
                except BackendUnavailable:
                    pass  # the layout is unknown: the US positions
            # A letter is the key that types it (ctrl+z is the key that types "z" on a German keyboard), but only when that
            # is a plain key: with Shift or AltGr the US position keeps the shortcut working on a non-Latin layout.
            if letter and found and (len(found) != 1 or found[0][1] or found[0][2]):
                found = None
            strokes.append(found[0] if found and len(found) == 1 else (KEYCODES[name], False, False))
        return strokes

    def ydotool(self, events: list[str]) -> None:
        if events:
            self.run(['ydotool', 'key', '-d', KEY_DELAY_MS, *events])

    def send_keys(self, names):
        if self.remote is not None:
            return self.portal_keys(names)
        codes = []
        for code, shift, altgr in self.key_strokes(names):
            # the Shift or AltGr a punctuation key needs in this layout is held like the keys named before it
            codes += [mod for needed, mod in ((shift, SHIFT_CODE), (altgr, ALTGR_CODE)) if needed and mod not in codes]
            codes.append(code)
        # released even when a later key fails: one call, so nothing stays held
        self.ydotool([f'{c}:1' for c in codes] + [f'{c}:0' for c in reversed(codes)])

    def text_strokes(self, text: str) -> list[list[tuple[int, bool, bool]]]:
        """The strokes of every character; ValueError naming the characters this layout cannot type."""
        keymap, strokes, missing = self.keymap(), [], []
        caps_lock = self.caps_lock()  # None when nothing tells: typed as with the lock off, which is the usual state
        for char in text:
            if char == '\n':
                strokes.append([(ENTER_CODE, False, False)])
            elif char == '\t':
                strokes.append([(TAB_CODE, False, False)])
            else:
                # a character Caps Lock leaves no way to (none is known) is typed as without the lock
                found = (caps_lock and keymap.strokes(char, True)) or keymap.strokes(char)
                if found is None:
                    missing.append(char)
                strokes.append(found or [])
        if missing:
            shown = ' '.join(dict.fromkeys(missing))
            raise ValueError(f'Your keyboard layout has no key for {shown}: on Wayland Tessera can only type '
                             f'characters your layout has (use a "clipboard" step and ctrl+v for the rest)')
        return strokes

    @staticmethod
    def events(strokes) -> list[str]:
        events = []
        for code, shift, altgr in strokes:
            mods = [SHIFT_CODE] * shift + [ALTGR_CODE] * altgr
            events += [f'{m}:1' for m in mods] + [f'{code}:1', f'{code}:0'] + [f'{m}:0' for m in reversed(mods)]
        return events

    def send_text(self, text, pause=0.0, wait=time.sleep):
        chars = text.replace('\r\n', '\n').replace('\r', '\n')
        if self.remote is not None:
            return self.portal_text(chars, pause, wait)
        strokes = self.text_strokes(chars)  # all of it first: nothing is typed when one character cannot be
        if pause:
            for n, char_strokes in enumerate(strokes):
                self.ydotool(self.events(char_strokes))
                if n + 1 < len(strokes) and wait(pause):
                    break
            return
        for start in range(0, len(strokes), TYPE_CHUNK):
            self.ydotool(self.events(s for char in strokes[start:start + TYPE_CHUNK] for s in char))
            if start + TYPE_CHUNK < len(strokes) and wait(0):
                break

    def send_mouse(self, op, x=0, y=0, amount=0):
        if self.remote is not None:
            return self.portal_mouse(op, x, y, amount)
        if op in MOUSE_BUTTONS:
            self.run(['ydotool', 'click', MOUSE_BUTTONS[op]])
        elif op == 'double':
            self.run(['ydotool', 'click', '--repeat', '2', '--next-delay', '25', MOUSE_BUTTONS['left']])
        elif op == 'scroll':
            if amount:  # positive is away from you, as on X11
                self.run(['ydotool', 'mousemove', '--wheel', '--', '0', str(int(amount))])
        elif op == 'move':
            self.run(['ydotool', 'mousemove', '--', str(int(x)), str(int(y))])
        elif op == 'moveto':
            # uinput has no absolute pointer: ydotool goes to the corner and moves from there, so pointer
            # acceleration can make it land a little off (a flat acceleration profile makes it exact)
            self.run(['ydotool', 'mousemove', '--absolute', '--', str(int(x)), str(int(y))])
        else:
            raise ValueError(f'Unknown mouse operation: {op}')

    # input through the RemoteDesktop portal, where ydotool is not installed
    def portal_keys(self, names) -> None:
        numbers = [keysym_number(name) for name in names]  # an unknown key is refused before anything is pressed
        pressed = []
        try:
            for number in numbers:
                self.remote.keysym(number, True)
                pressed.append(number)
        finally:
            for number in reversed(pressed):  # released even when a later key failed: nothing stays held
                self.remote.keysym(number, False)

    def portal_text(self, chars: str, pause: float, wait) -> None:
        for n, char in enumerate(chars):
            number = char_keysym(char)
            self.remote.keysym(number, True)
            self.remote.keysym(number, False)
            if n + 1 >= len(chars):
                break
            if pause:
                if wait(pause):
                    break
            else:
                self.sleep(PORTAL_KEY_GAP)
                if (n + 1) % PORTAL_TYPE_CHUNK == 0 and wait(0):
                    break

    def portal_mouse(self, op, x=0, y=0, amount=0) -> None:
        if op in BUTTONS:
            self.remote.button(op, True)
            self.remote.button(op, False)
        elif op == 'double':
            for _ in range(2):
                self.remote.button('left', True)
                self.remote.button('left', False)
                self.sleep(0.05)
        elif op == 'scroll':
            if amount:
                self.remote.scroll(amount)
        elif op == 'move':
            self.remote.move(x, y)
        elif op == 'moveto':
            raise BackendUnavailable('Moving the pointer to a screen position is not possible through the RemoteDesktop '
                                     'portal: it only allows relative moves. Use a relative move, or install ydotool.')
        else:
            raise ValueError(f'Unknown mouse operation: {op}')

    def set_clipboard(self, text):
        if shutil.which('wl-copy'):
            # wl-copy keeps the text and serves it from a background process, like xclip on X11
            self.run(['wl-copy'], stdin=text, detach=True)
            return
        qdbus = shutil.which('qdbus6') or shutil.which('qdbus')
        if qdbus:
            self.run([qdbus, 'org.kde.klipper', '/klipper', 'setClipboardContents', text])
            return
        raise BackendUnavailable('wl-copy is not installed: install the "wl-clipboard" package')

    # windows
    def kdotool(self, *args: str) -> str:
        if not self.plasma:
            raise BackendUnavailable(WINDOWS_MESSAGE)
        return self.run(['kdotool', *args])

    def active_window(self):
        if not self.plasma:
            return self.windows.active_window() if self.windows else None
        try:
            lines = self.kdotool('getactivewindow', 'getwindowid', 'getwindowpid', 'getwindowname').splitlines()
        except BackendUnavailable:
            raise
        except OSError:
            return None  # nothing has the focus, or the window has no process id
        if not lines or not lines[0].startswith('{'):
            return None
        pid = int(lines[1]) if len(lines) > 1 and lines[1].strip().isdigit() else 0
        return {'id': lines[0].strip(), 'pid': pid, 'title': lines[2] if len(lines) > 2 else ''}

    def find_window(self, pids):
        if not self.plasma:
            return self.windows.find_window(pids) if self.windows else None
        for pid in sorted(pids):
            try:
                found = self.kdotool('search', '--all', '--pid', str(pid), '--name', '.').split()
            except BackendUnavailable:
                raise
            except OSError:
                continue
            if found:
                return found[0]
        return None

    def window_op(self, window, op):
        if not self.plasma:
            if self.windows:
                return self.windows.window_op(window, op)
            raise BackendUnavailable(WINDOWS_MESSAGE)
        target = [window] if window else []
        front = [] if window else ['getactivewindow']
        if op == 'minimize':
            self.kdotool(*front, 'windowminimize', *target)
        elif op == 'focus':
            if not window:
                return False
            self.kdotool('windowactivate', window)
        elif op == 'close':
            self.kdotool(*front, 'windowclose', *target)
        elif op == 'maximize':
            self.kdotool(*front, 'windowstate', '--add', 'MAXIMIZED', *target)
        elif op == 'restore':
            if window:
                self.kdotool('windowactivate', window)  # also brings a minimized window back
            self.kdotool(*front, 'windowstate', '--remove', 'MAXIMIZED', '--remove', 'MINIMIZED', *target)
        elif op == 'topmost':
            self.kdotool(*front, 'windowstate', '--toggle', 'ABOVE', *target)
        elif op == 'next_monitor':
            if window:
                self.kdotool('windowactivate', window)
            # KWin's own action moves the window in front and keeps its size and place on the new screen
            self.run(['gdbus', 'call', '--session', '--dest', 'org.kde.kglobalaccel', '--object-path', '/component/kwin',
                      '--method', 'org.kde.kglobalaccel.Component.invokeShortcut', 'Window to Next Screen'])
        else:
            raise ValueError(f'Unknown window operation: {op}')
        return True
