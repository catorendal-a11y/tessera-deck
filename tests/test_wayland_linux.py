"""The Wayland backend: keys and text in the session's layout, the ydotool and kdotool commands it builds."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_marks import linux_only_module
linux_only_module(__name__)
import unittest

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


class InputTests(unittest.TestCase):
    def backend(self, layout='no'):
        fake = FakeRun()
        return wayland.WaylandBackend(fake, keymap=keymap(layout), plasma=True), fake

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
        self.assertEqual(no.keycode('minus'), 53)  # "-" sits left of right Shift on a Norwegian keyboard
        self.assertEqual(us.keycode('minus'), 12)
        self.assertEqual(no.keycode('equals'), 13)  # "=" needs Shift there: the US position is used

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
