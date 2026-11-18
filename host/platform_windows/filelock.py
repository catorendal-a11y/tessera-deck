"""A one-byte exclusive lock on an open file, for the single-instance lock on Windows.

`msvcrt` exists only on Windows, so it is imported when a lock is
taken, and this module imports on every system.
"""


def lock(handle) -> None:
    """Lock the first byte; raises OSError when another process holds it."""
    import msvcrt
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)


def unlock(handle) -> None:
    import msvcrt
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
