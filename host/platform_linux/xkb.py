"""The keyboard layout of the session, for a backend that sends raw key codes (ydotool on Wayland).

A uinput device sends key positions, not characters: the compositor turns them into characters with your layout. So
to type "@" on a Norwegian keyboard the backend has to press AltGr+2, and on a US one Shift+2. `Keymap` reads the
layout the session uses and answers which key and modifiers give a character. It uses libxkbcommon through ctypes
(every Wayland desktop has it), so the host needs no extra Python package.

The layout is read from XWayland (`xkbcomp`), which the compositor keeps in step with its own keymap. Without
XWayland it is the layout the session was set up with (`layout_names`). When nothing names one, typing is refused:
a guessed layout would type other characters than the ones asked for.
"""
from __future__ import annotations

import configparser
import ctypes
import ctypes.util
import json
import os
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

from platform_linux import BackendUnavailable

EVDEV_OFFSET = 8  # an XKB key code is the kernel's code plus 8
SHIFT, ALTGR = 'shift', 'altgr'
# Dead keys a layout uses for characters it has no key of their own for ("~" and "^" on Nordic keyboards):
# the dead key followed by Space gives the character alone, followed by a letter the accented letter.
DEAD_SPACING = {0xfe50: '`', 0xfe51: '´', 0xfe52: '^', 0xfe53: '~', 0xfe57: '¨'}
# With Space these two give the ASCII look-alike (' and "): the accent alone is the dead key pressed twice.
DEAD_TWICE = {0xfe51, 0xfe57}
DEAD_COMBINING = {'̀': 0xfe50, '́': 0xfe51, '̂': 0xfe52, '̃': 0xfe53, '̈': 0xfe57}
KEYPAD_SYMS = range(0xff80, 0xffbe)  # KP_Divide and the like: they type the same character, but programs treat them apart
SPACE_CODE = 57
# The keys of a real keyboard. A layout also names keys no keyboard has (a "$" key, a "€" key): they would win as
# the plainest way to a character, and nothing says the virtual keyboard can press them.
MAX_KEYCODE = 255


class _Names(ctypes.Structure):
    _fields_ = [(name, ctypes.c_char_p) for name in ('rules', 'model', 'layout', 'variant', 'options')]


_lib = None


def library():
    global _lib
    if _lib is None:
        path = ctypes.util.find_library('xkbcommon') or 'libxkbcommon.so.0'
        try:
            lib = ctypes.CDLL(path)
        except OSError as exc:
            raise BackendUnavailable('libxkbcommon is not installed: install the "libxkbcommon" package') from exc
        vp, u32 = ctypes.c_void_p, ctypes.c_uint32
        for name, res, args in (
                ('xkb_context_new', vp, [ctypes.c_int]),
                ('xkb_keymap_new_from_string', vp, [vp, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]),
                ('xkb_keymap_new_from_names', vp, [vp, ctypes.POINTER(_Names), ctypes.c_int]),
                ('xkb_keymap_unref', None, [vp]),
                ('xkb_context_unref', None, [vp]),
                ('xkb_keymap_min_keycode', u32, [vp]),
                ('xkb_keymap_max_keycode', u32, [vp]),
                ('xkb_keymap_num_layouts', u32, [vp]),
                ('xkb_keymap_num_levels_for_key', u32, [vp, u32, u32]),
                ('xkb_keymap_key_get_syms_by_level', ctypes.c_int, [vp, u32, u32, u32, ctypes.POINTER(ctypes.POINTER(u32))]),
                ('xkb_keymap_key_get_mods_for_level', ctypes.c_size_t, [vp, u32, u32, u32, ctypes.POINTER(u32), ctypes.c_size_t]),
                ('xkb_keymap_mod_get_index', u32, [vp, ctypes.c_char_p]),
                ('xkb_state_new', vp, [vp]),
                ('xkb_state_unref', None, [vp]),
                ('xkb_state_update_mask', ctypes.c_int, [vp, u32, u32, u32, u32, u32, u32]),
                ('xkb_state_key_get_one_sym', u32, [vp, u32]),
                ('xkb_keysym_to_utf32', u32, [u32])):
            function = getattr(lib, name)
            function.restype, function.argtypes = res, args
        _lib = lib
    return _lib


class Keymap:
    """Which key, with which of Shift and AltGr, types a character in one layout group. `locked` and `locked_dead`
    answer the same while Caps Lock is on, when a letter key gives the other case."""

    def __init__(self, keymap_text: bytes | None = None, names: dict | None = None, group: int = 0):
        lib = library()
        context = lib.xkb_context_new(0)
        if not context:
            raise BackendUnavailable('libxkbcommon could not start')
        try:
            if keymap_text:
                keymap = lib.xkb_keymap_new_from_string(context, keymap_text, 1, 0)
            else:
                given = _Names(*((names or {}).get(f, '').encode() or None for f, _ in _Names._fields_))
                keymap = lib.xkb_keymap_new_from_names(context, ctypes.byref(given), 0)
            if not keymap:
                raise BackendUnavailable('The keyboard layout of the session could not be read')
            try:
                self.layouts = lib.xkb_keymap_num_layouts(keymap)
                self.group = group if group < self.layouts else 0
                self.chars, self.dead, self.locked, self.locked_dead = self._read(lib, keymap)
            finally:
                lib.xkb_keymap_unref(keymap)
        finally:
            lib.xkb_context_unref(context)

    def _read(self, lib, keymap):
        shift = 1 << lib.xkb_keymap_mod_get_index(keymap, b'Shift')
        altgr = 0
        for name in (b'Mod5', b'LevelThree'):
            index = lib.xkb_keymap_mod_get_index(keymap, name)
            if index < 32:
                altgr |= 1 << index
        chars, dead = {}, {}
        masks = (ctypes.c_uint32 * 8)()
        for code in range(lib.xkb_keymap_min_keycode(keymap), min(lib.xkb_keymap_max_keycode(keymap), MAX_KEYCODE) + 1):
            for level in range(lib.xkb_keymap_num_levels_for_key(keymap, code, self.group)):
                syms = ctypes.POINTER(ctypes.c_uint32)()
                if lib.xkb_keymap_key_get_syms_by_level(keymap, code, self.group, level, ctypes.byref(syms)) != 1:
                    continue
                sym = syms[0]
                count = lib.xkb_keymap_key_get_mods_for_level(keymap, code, self.group, level, masks, len(masks))
                # the plainest way to reach the level with only Shift and AltGr: NumLock, Caps Lock and Ctrl+Alt are left out
                mods = sorted((masks[n] for n in range(count) if not masks[n] & ~(shift | altgr)), key=lambda m: bin(m).count('1'))
                if not mods:
                    continue
                self._note(lib, chars, dead, sym, (code - EVDEV_OFFSET, bool(mods[0] & shift), bool(mods[0] & altgr)))
        return chars, dead, *self._read_locked(lib, keymap, shift, altgr)

    def _read_locked(self, lib, keymap, shift, altgr):
        """The same tables with Caps Lock on. The levels of a key do not say what the lock does to it, so each key is
        asked with every combination of Shift and AltGr."""
        chars, dead = {}, {}
        lock_index = lib.xkb_keymap_mod_get_index(keymap, b'Lock')
        state = lib.xkb_state_new(keymap) if lock_index < 32 else None
        if not state:
            return chars, dead
        try:
            for code in range(lib.xkb_keymap_min_keycode(keymap), min(lib.xkb_keymap_max_keycode(keymap), MAX_KEYCODE) + 1):
                for with_shift, with_altgr in ((False, False), (True, False), (False, True), (True, True)):
                    lib.xkb_state_update_mask(state, shift * with_shift | altgr * with_altgr, 0, 1 << lock_index, 0, 0, self.group)
                    sym = lib.xkb_state_key_get_one_sym(state, code)
                    if sym:
                        self._note(lib, chars, dead, sym, (code - EVDEV_OFFSET, with_shift, with_altgr))
        finally:
            lib.xkb_state_unref(state)
        return chars, dead

    def _note(self, lib, chars, dead, sym, stroke):
        if sym in DEAD_SPACING:
            table, key = dead, sym
        elif sym in KEYPAD_SYMS:
            return
        else:
            char = lib.xkb_keysym_to_utf32(sym)
            if not char:
                return
            table, key = chars, chr(char)
        if key not in table or self.cost(stroke) < self.cost(table[key]):
            table[key] = stroke

    @staticmethod
    def cost(stroke):
        return (stroke[1] + stroke[2], stroke[0])

    def strokes(self, char: str, caps_lock: bool = False) -> list[tuple[int, bool, bool]] | None:
        """[(kernel key code, shift, altgr)] that type `char`, or None when this layout cannot type it. With
        `caps_lock` the strokes are the ones that give `char` while Caps Lock is on."""
        chars, dead = (self.locked, self.locked_dead) if caps_lock and self.locked else (self.chars, self.dead)
        if char in chars:
            return [chars[char]]
        for sym, spacing in DEAD_SPACING.items():
            if char == spacing and sym in dead:
                return [dead[sym], dead[sym] if sym in DEAD_TWICE else (SPACE_CODE, False, False)]
        parts = unicodedata.normalize('NFD', char)
        if len(parts) == 2 and parts[1] in DEAD_COMBINING and DEAD_COMBINING[parts[1]] in dead:
            base = self.strokes(parts[0], caps_lock)
            if base and len(base) == 1:
                return [dead[DEAD_COMBINING[parts[1]]], base[0]]
        return None


ASK = object()  # session_keymap asks the desktop which layout is in use
UNKNOWN_GROUP = ('This session has more than one keyboard layout and this desktop does not tell which one is in use, so '
                 'nothing is typed. Keep one layout, or use a "clipboard" step and ctrl+v.')
NO_LAYOUT = ('The keyboard layout of the session could not be read, so nothing is typed. Install xkbcomp '
             '("xorg-xkbcomp" on Arch, "x11-xkb-utils" on Debian or Ubuntu) or set XKB_DEFAULT_LAYOUT to your layout, for example "no".')


def session_keymap(run=subprocess.run, environ=None, group=ASK) -> Keymap:
    """The keymap the session types with right now, or of layout number `group`. None for `group` says that the
    layout in use is not known: fine with one layout, refused with more."""
    environ = os.environ if environ is None else environ
    if group is ASK:
        group = active_group(run, environ)
    keymap = None
    if environ.get('DISPLAY') and shutil.which('xkbcomp'):
        try:
            done = run(['xkbcomp', '-w0', environ['DISPLAY'], '-'], capture_output=True, timeout=5, check=False)
            if done.returncode == 0 and done.stdout:
                keymap = Keymap(keymap_text=done.stdout, group=group or 0)
        except (OSError, subprocess.SubprocessError):
            pass
    if keymap is None:
        names = layout_names(run, environ)
        if names is None:
            raise BackendUnavailable(NO_LAYOUT)
        keymap = Keymap(names=names, group=group or 0)
    if group is None and keymap.layouts > 1:
        raise BackendUnavailable(UNKNOWN_GROUP)
    return keymap


def layout_names(run=subprocess.run, environ=None) -> dict | None:
    """The layout the session was set up with, for a session without XWayland; None when nothing names one.

    XKB_DEFAULT_* is what sway and the other wlroots compositors read. Plasma has its keyboard settings (kxkbrc) and,
    with no layouts chosen there, follows the system's layout (localectl). Another desktop may have its own setting
    that differs from the system's, so localectl is asked on Plasma only."""
    environ = os.environ if environ is None else environ
    fields = ('rules', 'model', 'layout', 'variant', 'options')
    if environ.get('XKB_DEFAULT_LAYOUT'):
        return {f: environ.get(f'XKB_DEFAULT_{f.upper()}', '') for f in fields}
    if 'KDE' not in environ.get('XDG_CURRENT_DESKTOP', '').upper().split(':'):
        return None
    settings = configparser.RawConfigParser(strict=False)
    settings.optionxform = str
    try:
        home = environ.get('XDG_CONFIG_HOME') or Path(environ.get('HOME') or Path.home()) / '.config'
        settings.read_string((Path(home) / 'kxkbrc').read_text(encoding='utf-8'))
        chosen = dict(settings['Layout'])
    except (OSError, ValueError, KeyError, configparser.Error):
        chosen = {}
    if chosen.get('Use', '').lower() == 'true' and chosen.get('LayoutList'):
        return {'layout': chosen['LayoutList'], 'variant': chosen.get('VariantList', ''),
                'model': chosen.get('Model', ''), 'options': chosen.get('Options', '')}
    if not shutil.which('localectl'):
        return None
    try:
        done = run(['localectl', 'status'], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    found = {key.lower(): value.strip() for key, value in re.findall(r'X11 (Layout|Model|Variant|Options):(.*)', done.stdout or '')}
    if done.returncode != 0 or not re.fullmatch(r'[\w,]+', found.get('layout', '')):  # "(unset)" and "n/a" name none
        return None
    return found


def active_group(run=subprocess.run, environ=None) -> int | None:
    """The number of the layout in use when the session has more than one, or None when it cannot be read. Plasma,
    sway and Hyprland (since September 2025) tell; GNOME and the others have nothing to ask."""
    environ = os.environ if environ is None else environ
    try:
        if 'KDE' in environ.get('XDG_CURRENT_DESKTOP', '').upper().split(':') and shutil.which('gdbus'):
            done = run(['gdbus', 'call', '--session', '--dest', 'org.kde.keyboard', '--object-path', '/Layouts',
                        '--method', 'org.kde.KeyboardLayouts.getLayout'], capture_output=True, text=True, timeout=2, check=False)
            found = re.search(r'(\d+),?\)', done.stdout) if done.returncode == 0 else None  # "(uint32 1,)"
            return int(found.group(1)) if found else None
        if environ.get('SWAYSOCK') and shutil.which('swaymsg'):
            done = run(['swaymsg', '-t', 'get_inputs', '--raw'], capture_output=True, text=True, timeout=2, check=False)
            return _keyboard_group(json.loads(done.stdout), 'xkb_active_layout_index') if done.returncode == 0 else None
        if environ.get('HYPRLAND_INSTANCE_SIGNATURE') and shutil.which('hyprctl'):
            done = run(['hyprctl', 'devices', '-j'], capture_output=True, text=True, timeout=2, check=False)
            return _keyboard_group(json.loads(done.stdout)['keyboards'], 'active_layout_index') if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        pass
    return None


def _keyboard_group(devices, field) -> int | None:
    """These compositors keep a layout per keyboard: ydotool's own keyboard is the one the keys come from."""
    groups = [(device.get('name', ''), device[field]) for device in devices
              if isinstance(device, dict) and isinstance(device.get(field), int) and device[field] >= 0]
    for name, group in groups:
        if 'ydotool' in name.lower():
            return group
    return groups[0][1] if groups else None
