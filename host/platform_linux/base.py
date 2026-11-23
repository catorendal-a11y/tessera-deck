"""What the host needs from a desktop session: synthetic input, the clipboard and windows.

A backend turns these calls into the tools of one display server. The key names are the host's own vocabulary
(`input_common.KEY_NAMES`: ctrl, shift, alt, win, enter, f5, ...); a backend maps them to what its tools understand.
"""
from __future__ import annotations

from platform_linux import BackendUnavailable

MOUSE_OPERATIONS = ('left', 'right', 'middle', 'double', 'scroll', 'move', 'moveto')


class DesktopBackend:
    name = 'none'

    # input
    def send_keys(self, names: list[str]) -> None:
        """Press the keys in order, then release them in reverse (a hotkey such as ctrl+shift+t)."""
        raise NotImplementedError

    def send_text(self, text: str, pause: float = 0.0, wait=None) -> None:
        """Type `text`. `pause` seconds between characters; `wait(seconds)` returning true ends the typing."""
        raise NotImplementedError

    def send_mouse(self, op: str, x: int = 0, y: int = 0, amount: int = 0) -> None:
        raise NotImplementedError

    def set_clipboard(self, text: str) -> None:
        raise NotImplementedError

    # windows
    def active_window(self) -> dict | None:
        """{'id', 'pid', 'title'} of the window in front, or None."""
        raise NotImplementedError

    def find_window(self, pids: set[int]) -> str | None:
        """The id of the first visible, titled window that belongs to one of `pids`."""
        raise NotImplementedError

    def window_op(self, window: str | None, op: str) -> bool:
        """minimize, maximize, restore, close, topmost, next_monitor or focus on `window` (None: the one in front)."""
        raise NotImplementedError

    def check_windows(self) -> None:
        """Raise BackendUnavailable with what to install when the window questions can only ever answer "none"."""


class NoDesktopBackend(DesktopBackend):
    """No graphical session (a console, or an SSH login): input and windows are refused with a reason."""
    name = 'none'

    def _refuse(self, *_, **__):
        raise BackendUnavailable('No graphical session was found: start Tessera from your desktop session')

    send_keys = send_text = send_mouse = set_clipboard = _refuse

    def active_window(self):
        return None

    def find_window(self, pids):
        return None

    def window_op(self, window, op):
        return False
