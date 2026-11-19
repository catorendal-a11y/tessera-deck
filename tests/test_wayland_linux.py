"""The Wayland backend: keys and text in the session's layout, the ydotool and kdotool commands it builds."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_marks import linux_only_module
linux_only_module(__name__)
import os
import tempfile
import types
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from platform_linux import BackendUnavailable, wayland, xkb
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

    def test_a_desktop_that_does_not_tell_and_an_answer_that_cannot_be_read_give_the_first_layout(self):
        self.assertEqual(self.group({'XDG_CURRENT_DESKTOP': 'GNOME'}, 'gdbus', '(uint32 1,)'), 0)
        self.assertEqual(self.group({'SWAYSOCK': '/run/sway.sock'}, 'swaymsg', 'not json'), 0)
        self.assertEqual(self.group({'HYPRLAND_INSTANCE_SIGNATURE': 'x'}, 'hyprctl', '{"keyboards":[{"name":"k"}]}'), 0)


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

    def test_caps_lock_is_read_from_the_keyboard_leds(self):
        with tempfile.TemporaryDirectory() as folder:
            pattern = os.path.join(folder, '*-capslock')
            self.assertFalse(wayland.caps_lock_on(pattern))
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


if __name__ == '__main__':
    unittest.main()
