"""The host's key names (input_common.KEY_NAMES) as X keysyms. Both display servers use them: xdotool takes the names, the
RemoteDesktop portal takes the numbers. One table, so a new key name is added in one place."""
from __future__ import annotations

# name -> X keysym name
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

# X keysym name -> number, for the names above that are not a single character (a character's keysym is its code point)
NUMBERS = {'Control_L': 0xffe3, 'Shift_L': 0xffe1, 'Alt_L': 0xffe9, 'Super_L': 0xffeb, 'Return': 0xff0d, 'Tab': 0xff09,
           'Escape': 0xff1b, 'space': 0x20, 'BackSpace': 0xff08, 'Delete': 0xffff, 'Home': 0xff50, 'End': 0xff57,
           'Prior': 0xff55, 'Next': 0xff56, 'Left': 0xff51, 'Up': 0xff52, 'Right': 0xff53, 'Down': 0xff54,
           'comma': 0x2c, 'period': 0x2e, 'slash': 0x2f, 'grave': 0x60, 'bracketleft': 0x5b, 'bracketright': 0x5d,
           'minus': 0x2d, 'equal': 0x3d, 'semicolon': 0x3b, 'apostrophe': 0x27, 'backslash': 0x5c,
           'Insert': 0xff63, 'Print': 0xff61, 'Menu': 0xff67, 'Caps_Lock': 0xffe5,
           'XF86AudioMute': 0x1008ff12, 'XF86AudioLowerVolume': 0x1008ff11, 'XF86AudioRaiseVolume': 0x1008ff13,
           'XF86AudioPlay': 0x1008ff14, 'XF86AudioNext': 0x1008ff17, 'XF86AudioPrev': 0x1008ff16,
           'XF86AudioStop': 0x1008ff15}
NUMBERS.update({f'KP_{i}': 0xffb0 + i for i in range(10)})
NUMBERS.update({f'F{i}': 0xffbd + i for i in range(1, 25)})


def keysym_name(name: str) -> str:
    """The X keysym name of a host key name; ValueError for an unknown key."""
    try:
        return KEYSYMS[name]
    except KeyError:
        raise ValueError(f'Unknown key: {name!r}') from None


def keysym_number(name: str) -> int:
    """The keysym number of a host key name."""
    symbol = keysym_name(name)
    return NUMBERS[symbol] if symbol in NUMBERS else ord(symbol)


CONTROL = {'\n': 'Return', '\t': 'Tab', '\b': 'BackSpace', '\x1b': 'Escape', '\x7f': 'Delete'}


def char_keysym(char: str) -> int:
    """The keysym that types `char`: Return, Tab, BackSpace, Escape and Delete for their control characters, else the
    code point (Latin-1) or 0x01000000 + the code point (the rest of Unicode)."""
    if char in CONTROL:
        return NUMBERS[CONTROL[char]]
    code = ord(char)
    return code if code < 0x100 else 0x01000000 + code
