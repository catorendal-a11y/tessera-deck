"""Process-creation flags on Linux: there are none (the Windows ones hide the console window, start a new group ...).

The shared code passes `creationflags=NO_WINDOW` to subprocess everywhere; 0 is what every system but Windows accepts.
"""
NO_WINDOW = 0
NEW_PROCESS_GROUP = 0
DETACHED = 0
NEW_CONSOLE = 0
