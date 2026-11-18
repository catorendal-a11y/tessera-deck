"""File permissions on Windows."""
import subprocess
from pathlib import Path


def make_private(path) -> None:
    """Let only the owner read `path`; the file keeps the folder's permissions when that cannot be done."""
    from process_flags import NO_WINDOW
    try:
        # *S-1-3-4 is "owner rights": no user name to look up, and it follows the file's owner.
        subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', '*S-1-3-4:F'], check=True, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        try:
            Path(path).read_bytes()
        except OSError:  # never leave a file its own user cannot read
            subprocess.run(['icacls', str(path), '/reset'], check=False, timeout=10, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        pass  # the file then keeps the folder's permissions, as before
