"""File permissions on Linux (the Windows counterpart is platform_windows/files.py with the same functions)."""
import os


def make_private(path) -> None:
    """Let only the owner read `path`; the file keeps the folder's permissions when that cannot be done."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
