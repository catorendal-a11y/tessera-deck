"""The process-creation flags of this system: no console window, a new process group, detached, a new console.

Each is 0 where it means nothing, so `subprocess.Popen(..., creationflags=NO_WINDOW)` is safe to write everywhere.
"""
from platform_support import load

_flags = load('process_flags')
NO_WINDOW = _flags.NO_WINDOW
NEW_PROCESS_GROUP = _flags.NEW_PROCESS_GROUP
DETACHED = _flags.DETACHED
NEW_CONSOLE = _flags.NEW_CONSOLE
