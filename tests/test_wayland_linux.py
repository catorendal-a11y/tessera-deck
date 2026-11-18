"""The Wayland backend: keys and text in the session's layout, the ydotool and kdotool commands it builds.

The commands and the search for the session's layout are plain logic with a fake runner, so they run on every system.
The tests that need a real layout use libxkbcommon and skip themselves where it is missing.

Where ydotool is not installed, input goes through the RemoteDesktop portal: those tests use a fake portal session, and
the portal protocol runs against a scripted D-Bus connection. No desktop, no portal and no tool is needed."""
import contextlib
import json
import sys
from pathlib import Path
import os
import tempfile
import types
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from platform_linux import BackendUnavailable, keysyms, portal, wayland, xkb
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

    def test_a_character_types_as_its_code_point_and_the_two_control_characters_as_keys(self):
        self.assertEqual([keysyms.char_keysym(c) for c in 'aAø€\n\t'],
                         [0x61, 0x41, 0xf8, 0x01000000 + 0x20ac, RETURN, TAB])

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

    def test_ydotool_is_used_where_it_is_installed_and_the_portal_where_it_is_not(self):
        with unittest.mock.patch.object(wayland.shutil, 'which', return_value='/usr/bin/ydotool'):
            self.assertIsNone(wayland.session_backend().remote)
        with unittest.mock.patch.object(wayland.shutil, 'which', return_value=None):
            self.assertIsInstance(wayland.session_backend().remote, portal.RemoteDesktop)


class Message:
    def __init__(self, body=(), member=''):
        self.body, self.member = body, member


class FakeConnection:
    """What jeepney's blocking connection offers the portal code, answering like the portal."""
    unique_name = ':1.77'

    def __init__(self, devices=3, response=0):
        self.devices, self.response = devices, response
        self.calls, self.queue, self.closed = [], [], False
        self.matches = []

    def send_and_get_reply(self, message, timeout=None):
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

    def test_the_wheel_and_the_pointer_use_the_right_calls(self):
        connection = FakeConnection()
        rd = remote(connection, self.folder)
        rd.scroll(3)
        rd.move(4, -5)
        self.assertEqual(connection.calls[-2], ('NotifyPointerAxisDiscrete', ('/session/1', {}, 0, -3)))
        self.assertEqual(connection.calls[-1], ('NotifyPointerMotion', ('/session/1', {}, 4.0, -5.0)))

if __name__ == '__main__':
    unittest.main()
