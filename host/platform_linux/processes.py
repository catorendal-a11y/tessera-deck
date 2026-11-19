"""Processes and files on Linux: ending a command's whole group, opening a path or an address, the options a command is
started with (the Windows counterpart is platform_windows/processes.py with the same functions)."""
import os
import signal

# Does Popen.terminate() leave a plugin's child processes running? Not here: the plugin runs in its own session and
# SIGTERM reaches it first, so it may stop itself; kill_tree is the fallback.
STOP_BY_KILLING_TREE = False


PR_SET_NAME = 15
PROCESS_NAME_LENGTH = 15  # the kernel keeps 15 characters


def name_process(name: str) -> None:
    """Give this process the name `killall` and `pkill` look for. A program written in Python is otherwise called python,
    so `killall Tessera` found nothing and the only way to stop it was `killall python`, which stops every Python program."""
    try:
        import ctypes
        ctypes.CDLL(None).prctl(PR_SET_NAME, name.encode('utf-8')[:PROCESS_NAME_LENGTH], 0, 0, 0)
    except (OSError, AttributeError):
        pass  # a system without prctl keeps the name it has


def spawn_options() -> dict:
    """Extra keyword arguments for subprocess.Popen: the command gets its own session, so its group can be ended whole."""
    return {'start_new_session': True}


def kill_tree(pid: int) -> None:
    """End a command started with spawn_options() and everything it started, not just the shell."""
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def open_path(path) -> None:
    """Open a file or folder with the program the desktop has for it."""
    from platform_linux import programs
    programs.launch(str(path))


def open_target(target: str) -> None:
    """Open a file, folder, address or program of the application menu."""
    from platform_linux import programs
    programs.launch(target)


def edit_script(path: str) -> None:
    """Open a script in the desktop's editor for the file type."""
    open_path(path)


def notification_beep() -> None:
    """No sound on Linux: a timer that ran out is announced by the tray notice only."""
