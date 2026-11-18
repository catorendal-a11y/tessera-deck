"""A one-byte exclusive lock on an open file, for the single-instance lock on Windows.

The Linux counterpart is platform_linux/filelock.py. `msvcrt` exists only on Windows, so it is imported when a lock is
taken, and this module imports on every system.
"""


import os


def lock(handle) -> None:
    """Lock the first byte; raises OSError when another process holds it."""
    if os.name != 'nt':  # a development machine that is not Windows: the POSIX lock the host always used there
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    import msvcrt
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)


def unlock(handle) -> None:
    if os.name != 'nt':
        return  # closing the file releases a flock
    import msvcrt
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
