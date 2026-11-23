"""The Wayland backend: keys and text in the session's layout, the ydotool and kdotool commands it builds.

The commands and the search for the session's layout are plain logic with a fake runner, so they run on every system.
The tests that need a real layout use libxkbcommon and skip themselves where it is missing.

Where ydotool is not installed, input goes through the RemoteDesktop portal: those tests use a fake portal session, and
the portal protocol runs against a scripted D-Bus connection. No desktop, no portal and no tool is needed."""
import contextlib
import json
import subprocess
import sys
from pathlib import Path
import os
import tempfile
import threading
import time
import types
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from platform_linux import BackendUnavailable, gnome_windows, keysyms, portal, tools, wayland, xkb
import input_common


class FakeRun:
    def __init__(self, answers=None):
        self.calls, self.answers = [], answers or {}

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        for key, value in self.answers.items():
            if key in args:
                return value
        return ''


def keymap(layout):
    try:
        return xkb.Keymap(names={'layout': layout})
    except BackendUnavailable as exc:
        raise unittest.SkipTest(f'libxkbcommon or the {layout} layout is missing: {exc}') from exc


class KeymapTests(unittest.TestCase):
    def test_a_character_is_found_with_the_modifiers_of_its_layout(self):
        us, no = keymap('us'), keymap('no')
        self.assertEqual(us.strokes('@'), [(3, True, False)])   # Shift+2
        self.assertEqual(no.strokes('@'), [(3, False, True)])   # AltGr+2
        self.assertEqual(no.strokes('/'), [(8, True, False)])   # Shift+7
        self.assertEqual(no.strokes('ø'), [(39, False, False)])
        self.assertEqual(no.strokes('Å'), [(26, True, False)])
        self.assertIsNone(us.strokes('ø'))

    def test_a_character_behind_a_dead_key_is_the_dead_key_and_space_or_the_letter(self):
        no = keymap('no')
        self.assertEqual(no.strokes('~'), [(27, False, True), (57, False, False)])
        self.assertEqual(no.strokes('é'), [(13, False, True), (18, False, False)])

    def test_the_acute_accent_and_the_diaeresis_alone_are_their_dead_key_twice(self):
        # with Space they type ' and " (the Compose table every toolkit uses), not ´ and ¨
        no = keymap('no')
        self.assertEqual(no.strokes('´'), [(13, False, True), (13, False, True)])
        self.assertEqual(no.strokes('¨'), [(27, False, False), (27, False, False)])
        self.assertEqual(no.strokes('`'), [(13, True, False), (57, False, False)])

    def test_the_main_keys_win_over_the_keypad(self):
        self.assertEqual(keymap('us').strokes('-'), [(12, False, False)])

    def test_a_key_no_keyboard_has_is_not_used(self):
        no = keymap('no')  # the layout has a "$" key and a "€" key above the range of real keyboards
        self.assertEqual(no.strokes('$'), [(5, False, True)])   # AltGr+4
        self.assertEqual(no.strokes('€'), [(18, False, True)])  # AltGr+E
        self.assertEqual(no.strokes('*'), [(43, True, False)])

    def test_with_caps_lock_on_a_letter_is_typed_with_the_other_shift(self):
        no = keymap('no')
        self.assertEqual(no.strokes('a', caps_lock=True), [(30, True, False)])
        self.assertEqual(no.strokes('A', caps_lock=True), [(30, False, False)])
        self.assertEqual(no.strokes('Ø', caps_lock=True), [(39, False, False)])
        self.assertEqual(no.strokes('é', caps_lock=True), [(13, False, True), (18, True, False)])
        for char in '7/@~':  # Caps Lock leaves digits and symbols alone
            self.assertEqual(no.strokes(char, caps_lock=True), no.strokes(char), char)


def done(out='', code=0):
    return types.SimpleNamespace(returncode=code, stdout=out, stderr='')


class SessionLayoutTests(unittest.TestCase):
    """What the session types with when XWayland cannot say (no DISPLAY here, so xkbcomp is never asked)."""

    def names(self, environ, tools=(), run=None):
        with unittest.mock.patch.object(xkb.shutil, 'which', lambda tool: tool if tool in tools else None):
            return xkb.layout_names(run or (lambda *a, **k: self.fail('nothing is run')), environ)

    def test_the_variables_of_the_session_come_first(self):
        self.assertEqual(self.names({'XKB_DEFAULT_LAYOUT': 'no', 'XKB_DEFAULT_VARIANT': 'nodeadkeys'})['variant'], 'nodeadkeys')

    def test_plasma_uses_its_keyboard_settings_and_without_them_the_layout_of_the_system(self):
        with tempfile.TemporaryDirectory() as folder:
            environ = {'XDG_CURRENT_DESKTOP': 'KDE', 'XDG_CONFIG_HOME': folder}
            localectl = lambda *a, **k: done('   System Locale: LANG=nb_NO.UTF-8\n    VC Keymap: no\n   X11 Layout: no\n'
                                             '    X11 Model: pc105\n  X11 Variant: winkeys\n')
            self.assertEqual(self.names(environ, ['localectl'], localectl), {'layout': 'no', 'model': 'pc105', 'variant': 'winkeys'})
            Path(folder, 'kxkbrc').write_text('[Layout]\nLayoutList=us,no\nUse=true\nVariantList=,\n', encoding='utf-8')
            self.assertEqual(self.names(environ)['layout'], 'us,no')
            Path(folder, 'kxkbrc').write_text('[Layout]\nLayoutList=us,no\nUse=false\n', encoding='utf-8')
            self.assertEqual(self.names(environ, ['localectl'], localectl)['layout'], 'no')

    def test_a_layout_nobody_names_is_not_guessed(self):
        self.assertIsNone(self.names({'XDG_CURRENT_DESKTOP': 'sway'}, ['localectl']))  # the system's may not be sway's
        with tempfile.TemporaryDirectory() as folder:
            environ = {'XDG_CURRENT_DESKTOP': 'KDE', 'XDG_CONFIG_HOME': folder}
            self.assertIsNone(self.names(environ))
            self.assertIsNone(self.names(environ, ['localectl'], lambda *a, **k: done('   X11 Layout: (unset)\n')))
            with unittest.mock.patch.object(xkb.shutil, 'which', lambda tool: None), \
                    self.assertRaisesRegex(BackendUnavailable, 'XKB_DEFAULT_LAYOUT'):
                xkb.session_keymap(environ=environ, group=0)

    def test_with_several_layouts_and_no_way_to_tell_which_is_in_use_typing_is_refused(self):
        keymap('us')  # skips without libxkbcommon
        with unittest.mock.patch.object(xkb.shutil, 'which', lambda tool: None):
            for group in (None, xkb.ASK):  # told so, or found out: nothing answers on this desktop
                with self.assertRaisesRegex(BackendUnavailable, 'more than one keyboard layout'):
                    xkb.session_keymap(environ={'XKB_DEFAULT_LAYOUT': 'us,no', 'XDG_CURRENT_DESKTOP': 'GNOME'}, group=group)
            self.assertEqual(xkb.session_keymap(environ={'XKB_DEFAULT_LAYOUT': 'us,no'}, group=1).strokes('ø'), [(39, False, False)])
            one = xkb.session_keymap(environ={'XKB_DEFAULT_LAYOUT': 'no', 'XDG_CURRENT_DESKTOP': 'GNOME'})
            self.assertEqual(one.strokes('@'), [(3, False, True)])  # one layout needs no answer

    def group(self, environ, tool, out):
        with unittest.mock.patch.object(xkb.shutil, 'which', lambda name: name if name == tool else None):
            return xkb.active_group(lambda *a, **k: done(out), environ)

    def test_the_layout_in_use_is_asked_from_plasma_sway_and_hyprland(self):
        self.assertEqual(self.group({'XDG_CURRENT_DESKTOP': 'KDE'}, 'gdbus', '(uint32 1,)\n'), 1)
        inputs = '[{"type":"pointer","name":"Mouse"},{"type":"keyboard","name":"AT keyboard","xkb_active_layout_index":0},' \
                 '{"type":"keyboard","name":"ydotoold virtual device","xkb_active_layout_index":1}]'
        self.assertEqual(self.group({'SWAYSOCK': '/run/sway.sock'}, 'swaymsg', inputs), 1)  # the keyboard the keys come from
        devices = '{"mice":[],"keyboards":[{"name":"at-keyboard","main":true,"active_layout_index":2}]}'
        self.assertEqual(self.group({'HYPRLAND_INSTANCE_SIGNATURE': 'x'}, 'hyprctl', devices), 2)

    def test_a_desktop_that_does_not_tell_and_an_answer_that_cannot_be_read_are_unknown(self):
        self.assertIsNone(self.group({'XDG_CURRENT_DESKTOP': 'GNOME'}, 'gdbus', '(uint32 1,)'))
        self.assertIsNone(self.group({'XDG_CURRENT_DESKTOP': 'KDE'}, 'none', '(uint32 1,)'))  # no gdbus
        self.assertIsNone(self.group({'XDG_CURRENT_DESKTOP': 'KDE'}, 'gdbus', 'Error: no such name'))
        self.assertIsNone(self.group({'SWAYSOCK': '/run/sway.sock'}, 'swaymsg', 'not json'))
        # Hyprland before September 2025 has no active_layout_index
        self.assertIsNone(self.group({'HYPRLAND_INSTANCE_SIGNATURE': 'x'}, 'hyprctl', '{"keyboards":[{"name":"k"}]}'))


class InputTests(unittest.TestCase):
    def backend(self, layout='no', caps_lock=False):
        fake = FakeRun()
        return wayland.WaylandBackend(fake, keymap=keymap(layout), plasma=True, caps_lock=lambda: caps_lock), fake

    def test_every_host_key_name_has_a_key_code(self):
        self.assertEqual(sorted(n for n in input_common.KEY_NAMES if n not in wayland.KEYCODES), [])

    def test_a_hotkey_presses_in_order_and_releases_in_reverse_in_one_call(self):
        backend, fake = self.backend()
        backend.send_keys(['ctrl', 'shift', 't'])
        self.assertEqual(fake.calls, [['ydotool', 'key', '-d', wayland.KEY_DELAY_MS,
                                       '29:1', '42:1', '20:1', '20:0', '42:0', '29:0']])

    def test_punctuation_in_a_hotkey_is_the_key_that_types_it(self):
        no, _ = self.backend('no')
        us, _ = self.backend('us')
        self.assertEqual(no.key_strokes(['minus']), [(53, False, False)])  # "-" sits left of right Shift on a Norwegian keyboard
        self.assertEqual(us.key_strokes(['minus']), [(12, False, False)])
        self.assertEqual(no.key_strokes(['equals']), [(11, True, False)])  # "=" is Shift+0 there
        self.assertEqual(no.key_strokes(['grave']), [(41, False, False)])  # behind a dead key: the US position

    def test_a_letter_in_a_hotkey_is_the_key_that_types_it_in_the_layout(self):
        # German: z sits where a US keyboard has y (code 21) and y where it has z (44); French: a is the q position (16)
        class Layout:  # stands in for libxkbcommon: the keys of a QWERTZ keyboard that differ from US
            keys = {'z': (21, False, False), 'y': (44, False, False), 'a': (30, False, False), 'Z': (21, True, False)}

            def strokes(self, char, caps_lock=False):
                return [self.keys[char]] if char in self.keys else None
        fake = FakeRun()
        backend = wayland.WaylandBackend(fake, keymap=Layout(), plasma=True)
        self.assertEqual(backend.key_strokes(['ctrl', 'z']), [(29, False, False), (21, False, False)])
        self.assertEqual(backend.key_strokes(['y']), [(44, False, False)])
        self.assertEqual(backend.key_strokes(['q']), [(16, False, False)])  # the layout has no q key here: the US position
        self.assertEqual(backend.key_strokes(['5']), [(6, False, False)])   # digits stay on their position

    def test_a_letter_in_a_hotkey_follows_the_real_german_and_french_layouts(self):
        self.assertEqual(self.backend('de')[0].key_strokes(['z']), [(21, False, False)])
        self.assertEqual(self.backend('fr')[0].key_strokes(['a']), [(16, False, False)])

    def test_a_hotkey_holds_the_shift_or_altgr_its_punctuation_needs_in_the_layout(self):
        no, fake = self.backend('no')
        no.send_keys(['ctrl', 'slash'])       # "/" is Shift+7: never the US slash key, which types "-" there
        no.send_keys(['ctrl', 'shift', 'slash'])
        no.send_keys(['ctrl', 'lbracket'])    # "[" is AltGr+8
        self.assertEqual([call[4:] for call in fake.calls], [
            ['29:1', '42:1', '8:1', '8:0', '42:0', '29:0'],
            ['29:1', '42:1', '8:1', '8:0', '42:0', '29:0'],
            ['29:1', '100:1', '9:1', '9:0', '100:0', '29:0']])
        us, fake = self.backend('us')
        us.send_keys(['ctrl', 'slash'])
        self.assertEqual(fake.calls[0][4:], ['29:1', '53:1', '53:0', '29:0'])

    def test_a_hotkey_uses_the_us_positions_when_the_layout_cannot_be_read(self):
        fake = FakeRun()
        backend = wayland.WaylandBackend(fake, plasma=True)
        with unittest.mock.patch.object(xkb, 'active_group', return_value=0), \
                unittest.mock.patch.object(xkb, 'session_keymap', side_effect=BackendUnavailable('no layout')):
            backend.send_keys(['ctrl', 'minus'])
            with self.assertRaises(BackendUnavailable):
                backend.send_text('a')
        self.assertEqual(fake.calls, [['ydotool', 'key', '-d', wayland.KEY_DELAY_MS, '29:1', '12:1', '12:0', '29:0']])

    def test_the_layout_in_use_is_asked_for_every_operation(self):
        # a switch of layout is followed at once; the layouts themselves are not read again for each key
        maps, groups = {0: keymap('no'), 1: keymap('us')}, iter([0, 1, 1, 0])
        fake = FakeRun()
        backend = wayland.WaylandBackend(fake, plasma=True, caps_lock=lambda: False)
        with unittest.mock.patch.object(xkb, 'active_group', lambda: next(groups)), \
                unittest.mock.patch.object(xkb, 'session_keymap', side_effect=lambda group: maps[group]) as read:
            for _ in range(4):
                backend.send_text('@')
        self.assertEqual([call[4:] for call in fake.calls], [['100:1', '3:1', '3:0', '100:0'], ['42:1', '3:1', '3:0', '42:0'],
                                                             ['42:1', '3:1', '3:0', '42:0'], ['100:1', '3:1', '3:0', '100:0']])
        self.assertEqual(read.call_count, 2)

    def test_caps_lock_does_not_change_the_case_of_typed_text(self):
        for caps_lock, wanted in ((False, ['30:1', '30:0', '42:1', '30:1', '30:0', '42:0', '8:1', '8:0']),
                                  (True, ['42:1', '30:1', '30:0', '42:0', '30:1', '30:0', '8:1', '8:0'])):
            backend, fake = self.backend('no', caps_lock=caps_lock)
            backend.send_text('aA7')
            self.assertEqual(fake.calls[0][4:], wanted, caps_lock)

    def test_an_unknown_caps_lock_state_types_as_with_the_lock_off(self):
        backend, fake = self.backend('no', caps_lock=None)
        backend.send_text('aA')
        self.assertEqual(fake.calls[0][4:], ['30:1', '30:0', '42:1', '30:1', '30:0', '42:0'])

    def test_caps_lock_is_read_from_the_keyboard_leds(self):
        with tempfile.TemporaryDirectory() as folder:
            pattern = os.path.join(folder, '*-capslock')
            self.assertIsNone(wayland.caps_lock_on(pattern))  # no keyboard with the LED: nothing tells
            os.mkdir(os.path.join(folder, 'input1-capslock'))  # one that cannot be read does not tell either
            self.assertIsNone(wayland.caps_lock_on(pattern))
            Path(folder, 'input2-capslock').write_text('0\n')
            self.assertIs(wayland.caps_lock_on(pattern), False)
            Path(folder, 'input3-capslock').write_text('0\n')
            Path(folder, 'input9-capslock').write_text('1\n')
            self.assertTrue(wayland.caps_lock_on(pattern))
            Path(folder, 'input9-capslock').write_text('0\n')
            self.assertFalse(wayland.caps_lock_on(pattern))

    def test_an_unknown_key_is_refused_before_anything_is_pressed(self):
        backend, fake = self.backend()
        with self.assertRaises(ValueError):
            backend.send_keys(['ctrl', 'nonsense'])
        self.assertEqual(fake.calls, [])

    def test_text_is_typed_with_the_modifiers_of_the_layout(self):
        backend, fake = self.backend('no')
        backend.send_text('a@\n')
        self.assertEqual(fake.calls, [['ydotool', 'key', '-d', wayland.KEY_DELAY_MS,
                                       '30:1', '30:0', '100:1', '3:1', '3:0', '100:0', '28:1', '28:0']])

    def test_text_the_layout_cannot_type_is_refused_before_anything_is_typed(self):
        backend, fake = self.backend('us')
        with self.assertRaisesRegex(ValueError, 'no key for ø'):
            backend.send_text('abcø')
        self.assertEqual(fake.calls, [])

    def test_typing_goes_in_chunks_and_a_stop_request_ends_it(self):
        backend, fake = self.backend()
        backend.send_text('a' * 70, wait=lambda seconds: False)
        self.assertEqual(len(fake.calls), 3)
        backend, fake = self.backend()
        backend.send_text('a' * 70, wait=lambda seconds: True)
        self.assertEqual(len(fake.calls), 1)

    def test_typing_with_a_pause_sends_one_character_at_a_time_and_stops_when_asked(self):
        backend, fake = self.backend()
        waits = []
        backend.send_text('abc', 0.2, wait=lambda seconds: waits.append(seconds) or len(waits) == 2)
        self.assertEqual([call[-2:] for call in fake.calls], [['30:1', '30:0'], ['48:1', '48:0']])
        self.assertEqual(waits, [0.2, 0.2])

    def test_mouse_operations(self):
        backend, fake = self.backend()
        for args in (('left',), ('right',), ('double',), ('scroll', 0, 0, -2), ('move', 5, -4), ('moveto', 100, 200)):
            backend.send_mouse(*args)
        self.assertEqual(fake.calls, [
            ['ydotool', 'click', '0xC0'], ['ydotool', 'click', '0xC1'],
            ['ydotool', 'click', '--repeat', '2', '--next-delay', '25', '0xC0'],
            ['ydotool', 'mousemove', '--wheel', '--', '0', '-2'],
            ['ydotool', 'mousemove', '--', '5', '-4'], ['ydotool', 'mousemove', '--absolute', '--', '100', '200']])
        for op in input_common.MOUSE_OPERATIONS:
            backend.send_mouse(op, 1, 1, 1)
        with self.assertRaises(ValueError):
            backend.send_mouse('triple')


class WindowTests(unittest.TestCase):
    def test_the_active_window_is_read_with_its_process_and_title(self):
        fake = FakeRun({'getactivewindow': '{abc}\n777\nMy Title\n'})
        self.assertEqual(wayland.WaylandBackend(fake, plasma=True).active_window(),
                         {'id': '{abc}', 'pid': 777, 'title': 'My Title'})

    def test_no_active_window_gives_none(self):
        def refuse(args, **kwargs):
            raise OSError('kdotool failed')
        self.assertIsNone(wayland.WaylandBackend(refuse, plasma=True).active_window())

    def test_a_window_is_found_by_its_process(self):
        fake = FakeRun({'--pid': '{w1}\n{w2}\n'})
        self.assertEqual(wayland.WaylandBackend(fake, plasma=True).find_window({42}), '{w1}')
        self.assertEqual(fake.calls, [['kdotool', 'search', '--all', '--pid', '42', '--name', '.']])

    def test_operations_go_to_the_given_window_or_the_one_in_front(self):
        fake = FakeRun()
        backend = wayland.WaylandBackend(fake, plasma=True)
        backend.window_op('{w}', 'maximize')
        backend.window_op(None, 'topmost')
        self.assertEqual(fake.calls, [['kdotool', 'windowstate', '--add', 'MAXIMIZED', '{w}'],
                                      ['kdotool', 'getactivewindow', 'windowstate', '--toggle', 'ABOVE']])
        self.assertFalse(backend.window_op(None, 'focus'))

    def test_every_window_operation_of_the_host_is_handled(self):
        for op in input_common.WINDOW_OPERATIONS:
            self.assertTrue(wayland.WaylandBackend(FakeRun(), plasma=True).window_op('{w}', op), op)

    def test_a_desktop_without_kdotool_uses_its_windows_part(self):
        class Windows:
            def active_window(self):
                return {'id': '7', 'pid': 1, 'title': 'x'}

            def find_window(self, pids):
                return '7'

            def window_op(self, window, op):
                return True
        fake = FakeRun()
        backend = wayland.WaylandBackend(fake, plasma=False, windows=Windows())
        self.assertEqual(backend.active_window()['id'], '7')
        self.assertEqual(backend.find_window({1}), '7')
        self.assertTrue(backend.window_op('7', 'close'))
        self.assertEqual(fake.calls, [])  # kdotool is not asked

    def test_plasma_with_kdotool_does_not_use_a_windows_part(self):
        fake = FakeRun({'--pid': '{w1}\n'})
        self.assertEqual(wayland.WaylandBackend(fake, plasma=True, windows=object()).find_window({42}), '{w1}')


CTRL, SHIFT, RETURN, TAB = 0xffe3, 0xffe1, 0xff0d, 0xff09


class FakeRemote:
    def __init__(self):
        self.events = []

    def keysym(self, number, pressed):
        self.events.append(('key', number, pressed))

    def button(self, name, pressed):
        self.events.append(('button', name, pressed))

    def scroll(self, steps):
        self.events.append(('scroll', steps))

    def move(self, dx, dy):
        self.events.append(('move', dx, dy))


def portal_backend(**kwargs):
    """A backend whose input goes through the RemoteDesktop portal, as where ydotool is not installed."""
    remote = FakeRemote()
    return wayland.WaylandBackend(remote=remote, sleep=lambda seconds: None, **kwargs), remote


class KeysymTests(unittest.TestCase):
    def test_every_host_key_name_has_a_number_and_the_numbers_match_the_names(self):
        for name in input_common.KEY_NAMES:
            self.assertIsInstance(keysyms.keysym_number(name), int, name)
        try:
            from Xlib import XK
        except ImportError:
            return
        for name, symbol in keysyms.KEYSYMS.items():
            if not symbol.startswith('XF86'):  # python-xlib does not load the XF86 group by default
                self.assertEqual(keysyms.keysym_number(name), XK.string_to_keysym(symbol), name)

    def test_a_character_types_as_its_code_point_and_the_control_characters_as_keys(self):
        self.assertEqual([keysyms.char_keysym(c) for c in 'aAø€\n\t\b\x1b\x7f'],
                         [0x61, 0x41, 0xf8, 0x01000000 + 0x20ac, RETURN, TAB, 0xff08, 0xff1b, 0xffff])

    def test_an_unknown_key_is_refused(self):
        with self.assertRaises(ValueError):
            keysyms.keysym_number('hyper')


class PortalInputTests(unittest.TestCase):
    def test_a_hotkey_presses_in_order_and_releases_in_reverse(self):
        wl, remote = portal_backend()
        wl.send_keys(['ctrl', 'shift', 't'])
        self.assertEqual(remote.events, [('key', CTRL, True), ('key', SHIFT, True), ('key', 0x74, True),
                                         ('key', 0x74, False), ('key', SHIFT, False), ('key', CTRL, False)])

    def test_a_key_that_fails_still_releases_what_was_pressed(self):
        wl, remote = portal_backend()
        original = remote.keysym

        def failing(number, pressed):
            if number == 0x74 and pressed:
                raise OSError('refused')
            original(number, pressed)
        remote.keysym = failing
        with self.assertRaises(OSError):
            wl.send_keys(['ctrl', 't'])
        self.assertEqual(remote.events, [('key', CTRL, True), ('key', CTRL, False)])

    def test_an_unknown_key_presses_nothing(self):
        wl, remote = portal_backend()
        with self.assertRaises(ValueError):
            wl.send_keys(['ctrl', 'hyper'])
        self.assertEqual(remote.events, [])

    def test_text_types_every_character_including_ones_that_are_not_on_the_keyboard(self):
        wl, remote = portal_backend()
        wl.send_text('aø€\r\nb')
        pressed = [number for kind, number, down in remote.events if down]
        self.assertEqual(pressed, [0x61, 0xf8, 0x01000000 + 0x20ac, RETURN, 0x62])
        self.assertEqual(len(remote.events), 10)  # each character goes down and up

    def test_a_stop_request_ends_the_typing(self):
        wl, remote = portal_backend()
        wl.send_text('abcdef', pause=0.1, wait=lambda seconds: len(remote.events) >= 4)
        self.assertEqual([n for _, n, down in remote.events if down], [0x61, 0x62])

    def test_mouse_operations(self):
        wl, remote = portal_backend()
        wl.send_mouse('right')
        wl.send_mouse('double')
        wl.send_mouse('scroll', amount=3)
        wl.send_mouse('scroll', amount=0)
        wl.send_mouse('move', 5, -7)
        self.assertEqual(remote.events, [('button', 'right', True), ('button', 'right', False),
                                         ('button', 'left', True), ('button', 'left', False),
                                         ('button', 'left', True), ('button', 'left', False),
                                         ('scroll', 3), ('move', 5, -7)])

    def test_an_absolute_pointer_position_is_refused_with_a_reason_and_an_unknown_operation_is_an_error(self):
        wl, _ = portal_backend()
        with self.assertRaisesRegex(BackendUnavailable, 'relative'):
            wl.send_mouse('moveto', 10, 10)
        with self.assertRaises(ValueError):
            wl.send_mouse('fly')

    def test_ydotool_is_used_where_it_is_installed_and_its_daemon_is_up_and_the_portal_where_it_is_not(self):
        # the client looks for the daemon at $YDOTOOL_SOCKET, else $XDG_RUNTIME_DIR/.ydotool_socket (ydotool 1.0, Client/ydotool.c)
        with tempfile.TemporaryDirectory() as runtime:
            socket = Path(runtime, '.ydotool_socket')
            with unittest.mock.patch.object(wayland.shutil, 'which', return_value='/usr/bin/ydotool'):
                self.assertIsInstance(wayland.session_backend({'XDG_RUNTIME_DIR': runtime}).remote, portal.RemoteDesktop)
                socket.touch()  # the daemon is up
                self.assertIsNone(wayland.session_backend({'XDG_RUNTIME_DIR': runtime}).remote)
                self.assertIsNone(wayland.session_backend({'YDOTOOL_SOCKET': str(socket)}).remote)
                self.assertIsInstance(wayland.session_backend({'YDOTOOL_SOCKET': runtime + '/other'}).remote, portal.RemoteDesktop)
            with unittest.mock.patch.object(wayland.shutil, 'which', return_value=None):
                self.assertIsInstance(wayland.session_backend({'XDG_RUNTIME_DIR': runtime}).remote, portal.RemoteDesktop)

    def test_a_tool_that_explains_itself_on_stdout_is_shown_to_the_user(self):
        # ydotool 1.0 prints "Please check if ydotoold is running." on stdout and exits 2
        text = "failed to connect socket `/run/x': No such file or directory\nPlease check if ydotoold is running.\n"
        done = subprocess.CompletedProcess(['ydotool'], 2, stdout=text, stderr='')
        with unittest.mock.patch.object(tools.shutil, 'which', return_value='/usr/bin/ydotool'), \
                unittest.mock.patch.object(tools.subprocess, 'run', return_value=done):
            with self.assertRaisesRegex(OSError, 'ydotoold is running'):
                tools.run(['ydotool', 'key', '1:1'])


class Message:
    def __init__(self, body=(), member=''):
        self.body, self.member = body, member


class FakeConnection:
    """What jeepney's blocking connection offers the portal code, answering like the portal."""
    unique_name = ':1.77'

    def __init__(self, devices=3, response=0):
        self.devices, self.response = devices, response
        self.calls, self.queue, self.closed = [], [], False
        self.matches, self.limits = [], []

    def send_and_get_reply(self, message, timeout=None):
        self.limits.append(timeout)
        header = message.header.fields
        member = next((value for key, value in header.items() if getattr(key, 'name', '') == 'member'), '')
        if member == 'AddMatch':
            self.matches.append(True)
            return None
        self.calls.append((member, message.body))
        if member == 'CreateSession':
            self.queue.append(Message((self.response, {'session_handle': ('s', '/session/1')})))
        elif member == 'SelectDevices':
            self.queue.append(Message((0, {})))
        elif member == 'Start':
            self.queue.append(Message((self.response, {'devices': ('u', self.devices), 'restore_token': ('s', 'new-token')})
                                      if self.response == 0 else (self.response, {})))
        return None

    @contextlib.contextmanager
    def filter(self, rule, **kwargs):
        yield self.queue

    def recv_until_filtered(self, queue, timeout=None):
        if not queue:
            raise TimeoutError
        return queue.pop(0)

    def close(self):
        self.closed = True


def remote(connection, folder):
    return portal.RemoteDesktop(connect=lambda: connection, record=Path(folder) / 'remote-desktop.local.json')


class PortalTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name

    def test_the_session_is_opened_at_the_first_key_and_the_token_is_kept(self):
        connection = FakeConnection()
        rd = remote(connection, self.folder)
        self.assertEqual(connection.calls, [])  # nothing is asked until there is something to send
        rd.keysym(0x61, True)
        members = [member for member, _ in connection.calls]
        self.assertEqual(members, ['CreateSession', 'SelectDevices', 'Start', 'NotifyKeyboardKeysym'])
        select = connection.calls[1][1][1]
        self.assertEqual((select['types'], select['persist_mode']), (('u', 3), ('u', 2)))
        self.assertNotIn('restore_token', select)
        self.assertEqual(connection.calls[3][1], ('/session/1', {}, 0x61, 1))
        self.assertEqual(json.loads((Path(self.folder) / 'remote-desktop.local.json').read_text())['restore_token'], 'new-token')
        rd.keysym(0x61, False)
        self.assertEqual([m for m, _ in connection.calls].count('CreateSession'), 1)  # one session for all events

    def test_a_saved_token_is_sent_so_the_dialog_does_not_come_again(self):
        (Path(self.folder) / 'remote-desktop.local.json').write_text(json.dumps({'restore_token': 'old-token'}))
        connection = FakeConnection()
        remote(connection, self.folder).button('left', True)
        self.assertEqual(connection.calls[1][1][1]['restore_token'], ('s', 'old-token'))
        self.assertEqual(connection.calls[3], ('NotifyPointerButton', ('/session/1', {}, 0x110, 1)))

    def test_an_answered_no_is_reported_and_the_next_key_asks_again(self):
        connection = FakeConnection(response=1)
        rd = remote(connection, self.folder)
        with self.assertRaisesRegex(BackendUnavailable, 'not allowed'):
            rd.keysym(0x61, True)
        self.assertTrue(connection.closed)
        connection.response = 0
        rd.keysym(0x61, True)
        self.assertEqual(connection.calls[-1][0], 'NotifyKeyboardKeysym')

    def test_a_session_without_the_keyboard_is_refused(self):
        with self.assertRaisesRegex(BackendUnavailable, 'keyboard'):
            remote(FakeConnection(devices=2), self.folder).keysym(0x61, True)

    def test_a_dialog_nobody_answers_is_reported(self):
        connection = FakeConnection()
        connection.recv_until_filtered = lambda queue, timeout=None: (_ for _ in ()).throw(TimeoutError())
        with self.assertRaisesRegex(BackendUnavailable, 'did not answer'):
            remote(connection, self.folder).keysym(0x61, True)

    def test_a_session_the_desktop_ended_is_started_again_once(self):
        connection = FakeConnection()
        rd = remote(connection, self.folder)
        rd.keysym(0x61, True)
        original = connection.send_and_get_reply
        failures = []

        def flaky(message, timeout=None):
            member = next((v for k, v in message.header.fields.items() if getattr(k, 'name', '') == 'member'), '')
            if member == 'NotifyKeyboardKeysym' and not failures:
                failures.append(1)
                raise OSError('session closed')
            return original(message, timeout)
        connection.send_and_get_reply = flaky
        rd.keysym(0x62, True)
        self.assertEqual([m for m, _ in connection.calls].count('CreateSession'), 2)
        self.assertEqual(connection.calls[-1][1][2], 0x62)

    def test_an_error_reply_from_the_desktop_is_an_error_and_the_session_is_started_again(self):
        from jeepney import MessageType
        from jeepney.low_level import Header, HeaderFields, Message as WireMessage
        connection = FakeConnection()
        rd = remote(connection, self.folder)
        rd.keysym(0x61, True)
        original, failures = connection.send_and_get_reply, []

        def failing(message, timeout=None):
            member = next((v for k, v in message.header.fields.items() if getattr(k, 'name', '') == 'member'), '')
            if member == 'NotifyKeyboardKeysym' and not failures:
                failures.append(1)
                header = Header(0, MessageType.error, 0, {HeaderFields.error_name: 'org.freedesktop.DBus.Error.Failed',
                                                          HeaderFields.reply_serial: 1}, 0)
                return WireMessage(header, ())
            return original(message, timeout)
        connection.send_and_get_reply = failing
        rd.keysym(0x62, True)  # the error is raised, the session started once more, the key sent
        self.assertEqual([m for m, _ in connection.calls].count('CreateSession'), 2)
        self.assertEqual(connection.calls[-1][1][2], 0x62)

    def test_every_method_call_has_a_time_limit_and_only_the_dialog_gets_the_long_one(self):
        connection = FakeConnection()
        waits = []
        answer = connection.recv_until_filtered
        connection.recv_until_filtered = lambda queue, timeout=None: (waits.append(timeout), answer(queue))[1]
        remote(connection, self.folder).keysym(0x61, True)
        self.assertEqual(len(connection.limits), 7)  # AddMatch and the call, three times, and the key
        self.assertEqual(connection.limits, [portal.RESPONSE_WAIT] * 6 + [portal.EVENT_WAIT])
        self.assertEqual(waits, [portal.RESPONSE_WAIT, portal.RESPONSE_WAIT, portal.DIALOG_WAIT])

    def test_a_method_call_the_desktop_does_not_answer_closes_the_connection_and_the_next_key_tries_again(self):
        connection = FakeConnection()
        answer, silent = connection.send_and_get_reply, [True]

        def send(message, timeout=None):
            if silent[0]:
                raise TimeoutError('no reply')
            return answer(message, timeout)
        connection.send_and_get_reply = send
        rd = remote(connection, self.folder)
        with self.assertRaises(TimeoutError):
            rd.keysym(0x61, True)
        self.assertTrue(connection.closed)
        silent[0] = False
        rd.keysym(0x61, True)
        self.assertEqual(connection.calls[-1][0], 'NotifyKeyboardKeysym')

    def held_dialog(self):
        """A desktop whose dialog stays open until `answer` is set, and a session that does not wait for it."""
        connection, answer = FakeConnection(), threading.Event()
        reply = connection.recv_until_filtered

        def recv(queue, timeout=None):
            if connection.calls[-1][0] == 'Start':
                answer.wait(5)
            return reply(queue)
        connection.recv_until_filtered = recv
        rd = portal.RemoteDesktop(connect=lambda: connection, record=Path(self.folder) / 'remote-desktop.local.json', grace=0.05)
        self.addCleanup(self.opened, rd)  # after the answer: the thread writes into the folder, which is removed next
        self.addCleanup(answer.set)
        return rd, connection, answer

    def opened(self, rd):
        """Wait for the thread that opens the session; True when none is left."""
        for thread in threading.enumerate():
            if thread.name == 'portal-session':
                thread.join(5)
        return rd._opening is None and not any(thread.name == 'portal-session' for thread in threading.enumerate())

    def test_a_key_does_not_wait_for_the_dialog_and_works_once_it_is_answered(self):
        rd, connection, answer = self.held_dialog()
        began = time.monotonic()
        with self.assertRaisesRegex(BackendUnavailable, 'not ready yet'):
            rd.keysym(0x61, True)
        with self.assertRaisesRegex(BackendUnavailable, 'not ready yet'):
            rd.keysym(0x61, True)  # asked for already: no second dialog, and no wait at all
        self.assertLess(time.monotonic() - began, 2)
        free = []
        other = threading.Thread(target=lambda: free.append(rd._lock.acquire(timeout=1) and (rd._lock.release() or True)))
        other.start()
        other.join()
        self.assertEqual(free, [True])  # nothing holds the lock while the dialog is open
        self.assertEqual([m for m, _ in connection.calls].count('CreateSession'), 1)
        answer.set()
        self.assertTrue(self.opened(rd))
        rd.keysym(0x61, True)
        self.assertEqual([m for m, _ in connection.calls], ['CreateSession', 'SelectDevices', 'Start', 'NotifyKeyboardKeysym'])

    def test_a_dialog_refused_after_the_key_gave_up_is_logged_and_the_next_key_asks_again(self):
        rd, connection, answer = self.held_dialog()
        connection.devices = 2  # this dialog will be answered without the keyboard
        with self.assertRaisesRegex(BackendUnavailable, 'not ready yet'):
            rd.keysym(0x61, True)
        with self.assertLogs('platform_linux.portal', 'WARNING') as logged:
            answer.set()  # after the key has gone
            self.assertTrue(self.opened(rd))
        self.assertIn('keyboard', logged.output[0])
        self.assertIsNone(rd._session)
        connection.devices = 3
        rd.keysym(0x61, True)
        self.assertEqual(connection.calls[-1][0], 'NotifyKeyboardKeysym')

    def test_a_session_that_arrives_after_close_is_closed_and_not_used(self):
        rd, connection, answer = self.held_dialog()
        with self.assertRaisesRegex(BackendUnavailable, 'not ready yet'):
            rd.keysym(0x61, True)
        rd.close()
        self.assertFalse(connection.closed)  # the thread that opened it closes it
        answer.set()
        self.assertTrue(self.opened(rd))
        self.assertTrue(connection.closed)
        self.assertIsNone(rd._session)

    def test_the_session_bus_is_opened_with_a_time_limit_on_hello(self):
        from unittest import mock
        import dbus_client
        with mock.patch('jeepney.io.blocking.prep_socket', return_value='socket') as prepared, \
                mock.patch('jeepney.bus.get_bus', return_value='address'), \
                mock.patch.object(dbus_client, 'open_connection', return_value='connection') as hello:
            self.assertEqual(portal.open_connection(), 'connection')
        prepared.assert_called_once_with('address', timeout=dbus_client.HELLO_SECONDS)
        hello.assert_called_once_with('socket')
        with mock.patch('jeepney.io.blocking.prep_socket', return_value='socket'), \
                mock.patch('jeepney.bus.get_bus', return_value='address'), \
                mock.patch.object(dbus_client, 'open_connection', side_effect=OSError('the D-Bus did not answer Hello')):
            with self.assertRaisesRegex(BackendUnavailable, 'not reachable.*Hello'):
                portal.open_connection()
        self.assertIs(gnome_windows.GnomeWindows()._connect, portal.open_connection)  # the extension is asked through it too

    def test_the_wheel_and_the_pointer_use_the_right_calls(self):
        connection = FakeConnection()
        rd = remote(connection, self.folder)
        rd.scroll(3)
        rd.move(4, -5)
        self.assertEqual(connection.calls[-2], ('NotifyPointerAxisDiscrete', ('/session/1', {}, 0, -3)))
        self.assertEqual(connection.calls[-1], ('NotifyPointerMotion', ('/session/1', {}, 4.0, -5.0)))


class AbsentService(Exception):
    name = 'org.freedesktop.DBus.Error.ServiceUnknown'


class GnomeWindowsTests(unittest.TestCase):
    def windows(self, answers):
        calls = []

        def call(member, signature, body):
            calls.append((member, signature, body))
            answer = answers[member]
            if isinstance(answer, Exception):
                raise answer
            return (answer,)
        return gnome_windows.GnomeWindows(call=call), calls

    def test_the_window_in_front_is_read_from_the_extension(self):
        windows, _ = self.windows({'Active': json.dumps({'id': '12', 'pid': 345, 'title': 'Inbox', 'class': 'mail'})})
        self.assertEqual(windows.active_window(), {'id': '12', 'pid': 345, 'title': 'Inbox'})
        self.assertIsNone(self.windows({'Active': ''})[0].active_window())

    def test_a_window_of_a_process_is_found_by_its_pids(self):
        windows, calls = self.windows({'Find': '7'})
        self.assertEqual(windows.find_window({30, 10}), '7')
        self.assertEqual(calls, [('Find', 'ai', ([10, 30],))])
        self.assertIsNone(self.windows({'Find': ''})[0].find_window({1}))

    def test_an_operation_is_passed_on_with_the_window_or_an_empty_id_for_the_one_in_front(self):
        windows, calls = self.windows({'Operate': True})
        self.assertTrue(windows.window_op('7', 'maximize'))
        self.assertTrue(windows.window_op(None, 'close'))
        self.assertEqual(calls, [('Operate', 'ss', ('7', 'maximize')), ('Operate', 'ss', ('', 'close'))])
        self.assertFalse(self.windows({'Operate': False})[0].window_op('9', 'focus'))

    def test_without_the_extension_questions_get_nothing_and_a_key_says_what_to_install(self):
        windows, _ = self.windows({'Active': BackendUnavailable('x'), 'Find': BackendUnavailable('x'),
                                   'Operate': BackendUnavailable(gnome_windows.MISSING)})
        with self.assertLogs('platform_linux.gnome_windows', 'WARNING') as logged:
            self.assertIsNone(windows.active_window())
            self.assertIsNone(windows.find_window({1}))  # said once, not at every question
        self.assertEqual(len(logged.records), 1)
        with self.assertRaisesRegex(BackendUnavailable, r'--gnome-extension.*gnome-extensions enable'):
            windows.window_op(None, 'close')

    def test_a_window_key_without_the_extension_says_what_to_install_instead_of_no_such_window(self):
        from platform_linux import input as linux_input
        absent = BackendUnavailable(gnome_windows.MISSING)
        windows, _ = self.windows({'Active': absent, 'Find': absent, 'Operate': absent})
        backend = wayland.WaylandBackend(FakeRun(), plasma=False, windows=windows)
        firefox = types.SimpleNamespace(info={'pid': 5, 'name': 'firefox', 'exe': '/usr/bin/firefox'})
        with unittest.mock.patch.object(linux_input, 'backend', lambda: backend),                 unittest.mock.patch.object(linux_input.psutil, 'process_iter', return_value=[firefox]):
            for process in ('', 'firefox'):  # the window in front, and the window of a program
                with self.assertRaisesRegex(BackendUnavailable, r'gnome-extensions enable', msg=process):
                    linux_input.window_action('minimize', process)

    def test_a_window_key_with_the_extension_and_no_window_still_finds_none(self):
        from platform_linux import input as linux_input
        windows, _ = self.windows({'Active': '', 'Find': ''})
        backend = wayland.WaylandBackend(FakeRun(), plasma=False, windows=windows)
        firefox = types.SimpleNamespace(info={'pid': 5, 'name': 'firefox', 'exe': '/usr/bin/firefox'})
        with unittest.mock.patch.object(linux_input, 'backend', lambda: backend),                 unittest.mock.patch.object(linux_input.psutil, 'process_iter', return_value=[firefox]):
            self.assertFalse(linux_input.window_action('minimize'))
            self.assertFalse(linux_input.window_action('minimize', 'firefox'))

    def test_a_service_that_is_not_on_the_bus_is_the_missing_extension(self):
        class Connection:
            def send_and_get_reply(self, message, timeout=None):
                raise AbsentService()
        windows = gnome_windows.GnomeWindows(connect=lambda: Connection())
        with self.assertRaisesRegex(BackendUnavailable, 'extension'):
            windows.window_op('1', 'focus')

    def silent(self):
        sent = []

        class Connection:
            def send_and_get_reply(self, message, timeout=None):
                sent.append(next(v for k, v in message.header.fields.items() if getattr(k, 'name', '') == 'member'))
                raise TimeoutError('no reply')
        return gnome_windows.GnomeWindows(connect=lambda: Connection()), sent

    def test_an_operation_that_got_no_answer_is_not_sent_again(self):
        windows, sent = self.silent()
        with self.assertRaisesRegex(OSError, 'not known whether the window was changed'):
            windows.window_op('7', 'close')
        self.assertEqual(sent, ['Operate'])  # the Shell may have closed it: a second send could close the next window

    def test_a_question_that_got_no_answer_is_asked_once_more(self):
        windows, sent = self.silent()
        with self.assertRaisesRegex(OSError, 'did not answer'):
            windows.active_window()
        with self.assertRaisesRegex(OSError, 'did not answer'):
            windows.find_window({1})
        self.assertEqual(sent, ['Active', 'Active', 'Find', 'Find'])

    def failing(self, failure):
        sent = []

        class Connection:
            def send_and_get_reply(self, message, timeout=None):
                sent.append(1)
                raise failure
        return gnome_windows.GnomeWindows(connect=lambda: Connection()), sent

    def test_an_operation_is_sent_once_whatever_went_wrong(self):
        for failure, said in ((BrokenPipeError('the bus went away'), 'not known whether the window was changed'),
                              (ValueError('refused'), 'did not answer: refused')):
            with self.subTest(failure=failure):
                windows, sent = self.failing(failure)
                with self.assertRaisesRegex(OSError, said):
                    windows.window_op('7', 'focus')
                self.assertEqual(len(sent), 1)

    def test_gnome_gets_the_extension_part_and_another_desktop_none(self):
        from unittest import mock
        for desktop in ('GNOME', 'ubuntu:GNOME'):
            with mock.patch.dict('os.environ', {'XDG_CURRENT_DESKTOP': desktop}):
                self.assertIsInstance(wayland.desktop_windows(), gnome_windows.GnomeWindows, desktop)
        for desktop in ('KDE', 'sway', ''):
            self.assertIsNone(wayland.desktop_windows({'XDG_CURRENT_DESKTOP': desktop}), desktop)
        with mock.patch.dict('os.environ', {'XDG_CURRENT_DESKTOP': 'GNOME'}):
            self.assertIsInstance(wayland.session_backend().windows, gnome_windows.GnomeWindows)


class ExtensionFilesTests(unittest.TestCase):
    folder = Path(__file__).resolve().parents[1] / 'host/linux/gnome-extension/tessera-windows@tessera'

    def test_the_metadata_names_the_folder_and_the_shell_versions_it_was_tried_on(self):
        meta = json.loads((self.folder / 'metadata.json').read_text(encoding='utf-8'))
        self.assertEqual(meta['uuid'], self.folder.name)
        self.assertEqual(meta['shell-version'], ['51'])
        self.assertIn('GNOME 51 or newer', gnome_windows.MISSING)  # a user told to enable it learns it needs this version

    def test_the_extension_and_the_host_agree_on_the_bus_name_the_path_and_the_methods(self):
        code = (self.folder / 'extension.js').read_text(encoding='utf-8')
        self.assertIn(f"const NAME = '{gnome_windows.NAME}';", code)
        self.assertIn(f"const PATH = '{gnome_windows.PATH}';", code)
        for method in ('Active', 'Find', 'Operate'):
            self.assertIn(f'<method name="{method}">', code)
        for op in ('focus', 'minimize', 'maximize', 'restore', 'close', 'topmost', 'next_monitor'):
            self.assertIn(f"case '{op}':", code)  # every operation of input_common.WINDOW_OPERATIONS
        self.assertEqual(set(input_common.WINDOW_OPERATIONS), {'focus', 'minimize', 'maximize', 'restore', 'close', 'topmost', 'next_monitor'})


class TrayBackendTests(unittest.TestCase):
    """Which pystray backend a session gets, decided before pystray is imported."""

    def choose(self, env, watcher=True, folder='/usr/lib/python3/site-packages', typelib=True):
        from unittest import mock
        from platform_linux import tray
        path = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), path))
        with mock.patch.object(tray, 'watcher_present', return_value=watcher), \
                mock.patch.object(tray, 'WATCHER_WAIT', 0), \
                mock.patch.object(tray, 'system_gi_folder', return_value=folder), \
                mock.patch.object(tray, '_typelib_available', return_value=typelib), \
                mock.patch('platform_linux.notify.notify', return_value=True) as notice, \
                mock.patch.dict(sys.modules, {'gi': None}):
            return tray.choose_backend(env), notice, folder in sys.path

    def test_x11_keeps_pystrays_own_choice(self):
        self.assertEqual(self.choose({'XDG_SESSION_TYPE': 'x11'})[0], 'default')

    def test_a_backend_the_user_chose_is_left_alone(self):
        self.assertEqual(self.choose({'XDG_SESSION_TYPE': 'wayland', 'PYSTRAY_BACKEND': 'gtk'})[0], 'gtk')

    def test_wayland_with_a_tray_host_uses_appindicator_and_adds_the_system_gi_at_the_end_of_the_path(self):
        env = {'XDG_SESSION_TYPE': 'wayland'}
        backend, notice, added = self.choose(env)
        self.assertEqual((backend, env['PYSTRAY_BACKEND'], added), ('appindicator', 'appindicator', True))
        self.assertEqual(sys.path[-1], '/usr/lib/python3/site-packages')
        notice.assert_not_called()

    def test_plasma_keeps_the_x11_icon_whose_left_click_opens_the_editor(self):
        env = {'XDG_SESSION_TYPE': 'wayland', 'XDG_CURRENT_DESKTOP': 'KDE'}
        backend, notice, added = self.choose(env, watcher=False)
        self.assertEqual((backend, env['PYSTRAY_BACKEND'], added), ('xorg', 'xorg', False))
        notice.assert_not_called()

    def test_a_tray_host_that_comes_a_little_later_is_waited_for(self):
        from unittest import mock
        from platform_linux import tray
        now = [0.0]

        def sleep(seconds):
            now[0] += seconds
        answers = iter([False, False, True])
        with mock.patch.object(tray, 'watcher_present', side_effect=lambda: next(answers)):
            self.assertTrue(tray.wait_for_watcher(10, sleep=sleep, clock=lambda: now[0]))
        with mock.patch.object(tray, 'watcher_present', return_value=False):
            self.assertFalse(tray.wait_for_watcher(1, sleep=sleep, clock=lambda: now[0]))

    def test_wayland_without_a_tray_host_says_so_once_and_chooses_nothing(self):
        env = {'XDG_SESSION_TYPE': 'wayland'}
        backend, notice, _ = self.choose(env, watcher=False)
        self.assertEqual((backend, 'PYSTRAY_BACKEND' in env), ('none', False))
        self.assertIn('AppIndicator', notice.call_args.args[0])

    def test_without_a_tray_host_the_tray_program_runs_with_an_icon_that_draws_nothing(self):
        from pystray._base import Icon, Menu
        from platform_linux import tray
        from PIL import Image
        image = Image.new('RGBA', (8, 8))
        icon = tray.no_icon(Icon)('tessera', image, 'Tessera', menu=Menu(lambda: []))
        loop = threading.Thread(target=icon.run, daemon=True)
        loop.start()
        deadline = time.monotonic() + 5
        while not icon._running and time.monotonic() < deadline:  # pystray's stop does nothing before the loop runs
            time.sleep(0.005)
        try:
            icon.title, icon.icon = 'Tessera — connected', image  # what the poll thread sets
            icon.update_menu()
            self.assertTrue(loop.is_alive())  # it waits, as a real icon's loop does
        finally:
            icon.stop()
            loop.join(5)
        self.assertFalse(loop.is_alive())

    def test_the_tray_program_takes_none_as_no_icon_before_it_imports_pystray(self):
        source = (Path(__file__).resolve().parents[1] / 'host/tessera_tray.py').read_text(encoding='utf-8')
        chosen, imported = source.index("BACKEND == 'none'"), source.index('import pystray')
        self.assertLess(chosen, imported)
        self.assertNotIn("PYSTRAY_BACKEND'] = 'none'", source)
        self.assertIn("del os.environ['PYSTRAY_BACKEND']", source)  # a tray started from this one chooses again

    def test_wayland_without_gi_or_the_typelib_names_the_x11_icon(self):
        # pystray's own choice would not do: with the system gi on the path its appindicator backend stops on the missing
        # library with a ValueError, which pystray does not catch
        for missing in ({'folder': None}, {'typelib': False}):
            with self.subTest(**missing):
                env = {'XDG_SESSION_TYPE': 'wayland'}
                self.assertEqual((self.choose(env, **missing)[0], env['PYSTRAY_BACKEND']), ('xorg', 'xorg'))


if __name__ == '__main__':
    unittest.main()
