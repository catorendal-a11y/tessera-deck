"""'Move the pointer to' must land on the pixel the user typed, also when Windows scales the display above 100%."""
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
    def test_a_typed_pixel_becomes_the_matching_absolute_position(self):
        left, top, width, height = json.loads(subprocess.check_output([sys.executable, '-c', PHYSICAL], text=True))
        x, y = left + width // 2, top + height // 2
        sent = []
        win_input.send_mouse('moveto', x, y, press=lambda *args, **kw: sent.append(args))
        flags, abs_x, abs_y = sent[0]
        self.assertEqual(abs_x, round((x - left) * 65535 / (width - 1)))
        self.assertEqual(abs_y, round((y - top) * 65535 / (height - 1)))

    def test_the_calling_thread_keeps_its_own_dpi_awareness(self):
        user32 = win_input.user32
        before = user32.GetThreadDpiAwarenessContext()
        win_input.send_mouse('moveto', 10, 10, press=lambda *args, **kw: None)
        self.assertEqual(user32.GetThreadDpiAwarenessContext(), before)


if __name__ == '__main__':
    unittest.main()
