"""Windows process-creation flags: no console window, a new process group, detached, a new console.

Each is 0 on every other system, so `subprocess.Popen(..., creationflags=NO_WINDOW)` is safe to write everywhere.
"""
import subprocess

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
NEW_PROCESS_GROUP = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
DETACHED = getattr(subprocess, 'DETACHED_PROCESS', 0)
NEW_CONSOLE = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)
