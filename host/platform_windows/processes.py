"""Processes and files on Windows: ending a command's whole tree, opening a script in its editor."""
import os
import subprocess
import sys

# Popen.terminate() ends only the plugin itself and leaves its child processes running: kill the whole tree instead.
# Only where taskkill exists: another system that loads this package (a development machine) keeps terminate-and-wait.
STOP_BY_KILLING_TREE = sys.platform == 'win32'


def spawn_options() -> dict:
    """Extra keyword arguments for subprocess.Popen: no console window, and a new process group."""
    from process_flags import NEW_PROCESS_GROUP, NO_WINDOW
    return {'creationflags': NO_WINDOW | NEW_PROCESS_GROUP}


def kill_tree(pid: int) -> None:
    """End a process and everything it started (taskkill /T), without a console window."""
    if os.name != 'nt':  # a development machine that is not Windows: end the process itself
        import signal
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        return
    subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def edit_script(path: str) -> None:
    """Open a script in the user's editor: the file type's edit verb, else Notepad."""
    try:
        os.startfile(path, 'edit')
    except OSError:
        subprocess.Popen(['notepad.exe', path])


def open_target(target: str) -> None:
    """Open a file, folder, address or program the way the shell does, and find a program that moved."""
    from action_preview import URI_SCHEME
    from platform_windows.programs import locate
    # %NAME% only in a path: in an address it would send this PC's environment to the site
    expanded = target if URI_SCHEME.match(target) else os.path.expandvars(target)
    os.startfile(expanded if os.path.exists(expanded) else locate(expanded) or expanded)


def open_path(path) -> None:
    """Open a file or folder with the program Windows has for it."""
    os.startfile(path)  # noqa: S606 - the user's own file or folder


def notification_beep() -> None:
    """The system "asterisk" sound, for a timer that ran out."""
    if os.name != 'nt':
        return
    import winsound
    winsound.MessageBeep(winsound.MB_ICONASTERISK)
