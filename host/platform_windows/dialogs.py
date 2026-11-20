"""Message boxes on Windows."""
import ctypes


def ask_yes_no(text: str, title: str = 'Tessera') -> bool:
    """A Yes/No question in front of everything (MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND | MB_TOPMOST)."""
    answer = ctypes.windll.user32.MessageBoxW(None, text, title, 0x4 | 0x20 | 0x10000 | 0x40000)
    return answer == 6  # IDYES
