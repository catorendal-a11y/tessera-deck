"""The script types a script step can run, and how a script path is written. Shared by every system; what runs each type
is platform_windows/programs.py (py launcher, cmd, AutoHotkey ...) or platform_linux/scripts.py (python3, bash, node ...)."""
import re

from platform_support import load

SCRIPT_SUFFIXES = ('.py', '.pyw', '.ps1', '.bat', '.cmd', '.ahk', '.js') + load('labels').SCRIPT_EXTRA_SUFFIXES
BATCH_SUFFIXES = ('.bat', '.cmd')
SCRIPT_VARIABLE = re.compile(r'%([^%\s]+)%')  # %NAME% only: $NAME is a legal folder name, so expandvars is not used


def script_text(path: str) -> str:
    """A script step's path as typed: without the spaces around it and the quotes of Explorer's Copy as path."""
    return path.strip().strip('"').strip()
