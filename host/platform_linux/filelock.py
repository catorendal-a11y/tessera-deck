"""An exclusive lock on an open file, for the single-instance lock on Linux (flock; the Windows counterpart is
platform_windows/filelock.py). The kernel drops the lock when the process dies.

`fcntl` exists only on POSIX systems, so it is imported when a lock is taken, and this module imports on every system."""


def lock(handle) -> None:
    """Raises OSError when another process holds the lock."""
    import fcntl
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock(handle) -> None:
    import fcntl
    fcntl.flock(handle, fcntl.LOCK_UN)
