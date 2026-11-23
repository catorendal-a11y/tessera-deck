"""'Move the pointer to' must land on the pixel the user typed, also when Windows scales the display above 100%."""
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))

from platform_windows import input as win_input  # noqa: E402

# a separate process that declares itself per-monitor DPI aware sees the real pixels of the virtual screen
PHYSICAL = ('import ctypes, json; u = ctypes.windll.user32; u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)); '
            'print(json.dumps([u.GetSystemMetrics(i) for i in (76, 77, 78, 79)]))')


@unittest.skipUnless(sys.platform == 'win32', 'needs the Windows GetSystemMetrics')
class MoveToTests(unittest.TestCase):
    def test_every_typed_pixel_lands_on_itself(self):
        # Windows turns the absolute value v back into the pixel floor(v * size / 65536) of the virtual screen.
        left, top, width, height = json.loads(subprocess.check_output([sys.executable, '-c', PHYSICAL], text=True))
        for x, y in ((left, top), (left + 1, top + 1), (left + width // 2, top + height // 2),
                     (left + width - 1, top + height - 1)):
            sent = []
            win_input.send_mouse('moveto', x, y, press=lambda *args, sent=sent, **kw: sent.append(args))
            flags, abs_x, abs_y = sent[0]
            self.assertEqual((left + abs_x * width // 65536, top + abs_y * height // 65536), (x, y))
            self.assertLessEqual(max(abs_x, abs_y), 65535)

    def test_the_input_is_sent_while_the_thread_sees_real_pixels(self):
        # A DPI-unaware thread's SendInput is mapped through the scaled screen: on a 150% display the pointer landed
        # at 1.5 times the typed pixel, so the metrics and the input must both use per-monitor awareness.
        user32 = win_input.user32
        user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        seen = []
        win_input.send_mouse('moveto', 10, 10, press=lambda *args, **kw: seen.append(
            user32.AreDpiAwarenessContextsEqual(user32.GetThreadDpiAwarenessContext(), ctypes.c_void_p(-4))))
        self.assertEqual(seen, [1])

    def test_the_calling_thread_keeps_its_own_dpi_awareness(self):
        user32 = win_input.user32
        before = user32.GetThreadDpiAwarenessContext()
        win_input.send_mouse('moveto', 10, 10, press=lambda *args, **kw: None)
        self.assertEqual(user32.GetThreadDpiAwarenessContext(), before)


if __name__ == '__main__':
    unittest.main()
