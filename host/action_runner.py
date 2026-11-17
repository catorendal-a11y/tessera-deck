"""Running external commands for actions: bounded, cancellable and killed as a whole process tree."""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time

IS_WINDOWS = os.name == 'nt'
POLL_SECONDS = 0.1
STDERR_TAIL = 200


class Busy(RuntimeError):
    """The host cannot take more work right now (queue full or too many slow actions)."""


class CommandFailed(RuntimeError):
    pass


def kill_tree(process: subprocess.Popen) -> None:
    """Stop a command and everything it started; `shell=True` alone only kills the shell."""
    if process.poll() is not None:
        return
    if IS_WINDOWS:
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        process.kill()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def run_command(command, timeout: float, stop: threading.Event, shell: bool = True, cwd: str | None = None) -> None:
    """Run `command` until it exits, `timeout` passes or `stop` is set; raises CommandFailed otherwise."""
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
    # stderr goes to a file, not a pipe: a program launched with `start` inherits a pipe and would hold it open
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, shell=shell, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=errors, creationflags=flags, cwd=cwd)
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    process.wait(timeout=POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    if stop.is_set():
                        raise CommandFailed('Stopped before the command finished') from None
                    if time.monotonic() >= deadline:
                        raise CommandFailed(f'The command did not finish within {timeout:g} seconds') from None
        finally:
            kill_tree(process)
        errors.seek(0)
        stderr = errors.read()
    if process.returncode:
        tail = (stderr or b'').decode('utf-8', 'replace').strip()[-STDERR_TAIL:]
        raise CommandFailed(f'The command exited with code {process.returncode}' + (f': {tail}' if tail else ''))


def script_path(script: str) -> str:
    """The full path of a script step's file, with %NAME% expanded; ValueError says what is wrong with it."""
    from program_locator import SCRIPT_SUFFIXES
    expanded = os.path.expandvars(script.strip())
    if not os.path.isabs(expanded):
        raise ValueError('Use the full path of the script file')
    if not expanded.lower().endswith(SCRIPT_SUFFIXES):
        raise ValueError(f'Script type is not supported. Use {", ".join(SCRIPT_SUFFIXES)}')
    if not os.path.isfile(expanded):
        raise ValueError(f'The script was not found: {expanded}')
    return expanded


def run_script(script: str, timeout: float, stop: threading.Event) -> None:
    """Run a script file without a window, in its own folder, with the limits and errors of `run_command`."""
    from program_locator import script_command
    try:
        path = script_path(script)
        argv = script_command(path)
    except ValueError as exc:
        raise CommandFailed(str(exc)) from exc
    run_command(argv, timeout, stop, shell=False, cwd=os.path.dirname(path))


def edit_script(script: str) -> None:
    """Open a script in the user's editor: the file type's edit verb, else Notepad."""
    path = script_path(script)
    try:
        os.startfile(path, 'edit')
    except OSError:
        subprocess.Popen(['notepad.exe', path])
