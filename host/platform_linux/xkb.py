"""The keyboard layout of the session, for a backend that sends raw key codes (ydotool on Wayland).

A uinput device sends key positions, not characters: the compositor turns them into characters with your layout. So
to type "@" on a Norwegian keyboard the backend has to press AltGr+2, and on a US one Shift+2. `Keymap` reads the
layout the session uses and answers which key and modifiers give a character. It uses libxkbcommon through ctypes
(every Wayland desktop has it), so the host needs no extra Python package.

The layout is read from XWayland (`xkbcomp`), which the compositor keeps in step with its own keymap; without
XWayland it falls back to the XKB_DEFAULT_* variables, then to "us".
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import shutil
import subprocess
import unicodedata

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
                ('xkb_keysym_to_utf32', u32, [u32])):
            function = getattr(lib, name)
            function.restype, function.argtypes = res, args
        _lib = lib
    return _lib


class Keymap:
    """Which key, with which of Shift and AltGr, types a character in one layout group."""

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
                self.group = group if group < lib.xkb_keymap_num_layouts(keymap) else 0
                self.chars, self.dead = self._read(lib, keymap)
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
        for code in range(lib.xkb_keymap_min_keycode(keymap), lib.xkb_keymap_max_keycode(keymap) + 1):
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
                stroke = (code - EVDEV_OFFSET, bool(mods[0] & shift), bool(mods[0] & altgr))
                if sym in DEAD_SPACING:
                    table, key = dead, sym
                elif sym in KEYPAD_SYMS:
                    continue
                else:
                    char = lib.xkb_keysym_to_utf32(sym)
                    if not char:
                        continue
                    table, key = chars, chr(char)
                if key not in table or self.cost(stroke) < self.cost(table[key]):
                    table[key] = stroke
        return chars, dead

    @staticmethod
    def cost(stroke):
        return (stroke[1] + stroke[2], stroke[0])

    def strokes(self, char: str) -> list[tuple[int, bool, bool]] | None:
        """[(kernel key code, shift, altgr)] that type `char`, or None when this layout cannot type it."""
        if char in self.chars:
            return [self.chars[char]]
        for sym, spacing in DEAD_SPACING.items():
            if char == spacing and sym in self.dead:
                return [self.dead[sym], self.dead[sym] if sym in DEAD_TWICE else (SPACE_CODE, False, False)]
        parts = unicodedata.normalize('NFD', char)
        if len(parts) == 2 and parts[1] in DEAD_COMBINING and DEAD_COMBINING[parts[1]] in self.dead:
            base = self.strokes(parts[0])
            if base and len(base) == 1:
                return [self.dead[DEAD_COMBINING[parts[1]]], base[0]]
        return None


def session_keymap(run=subprocess.run, environ=None) -> Keymap:
    """The keymap the session types with right now."""
    environ = os.environ if environ is None else environ
    group = active_group(run)
    if environ.get('DISPLAY') and shutil.which('xkbcomp'):
        try:
            done = run(['xkbcomp', '-w0', environ['DISPLAY'], '-'], capture_output=True, timeout=5, check=False)
            if done.returncode == 0 and done.stdout:
                return Keymap(keymap_text=done.stdout, group=group)
        except (OSError, subprocess.SubprocessError):
            pass
    names = {f: environ.get(f'XKB_DEFAULT_{f.upper()}', '') for f in ('rules', 'model', 'layout', 'variant', 'options')}
    return Keymap(names=names, group=group)


def active_group(run=subprocess.run) -> int:
    """The layout in use when you have more than one (Plasma tells; elsewhere the first)."""
    if not shutil.which('gdbus'):
        return 0
    try:
        done = run(['gdbus', 'call', '--session', '--dest', 'org.kde.keyboard', '--object-path', '/Layouts',
                    '--method', 'org.kde.KeyboardLayouts.getLayout'], capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return 0
    found = re.search(r'(\d+),?\)', done.stdout) if done.returncode == 0 else None  # "(uint32 1,)"
    return int(found.group(1)) if found else 0
