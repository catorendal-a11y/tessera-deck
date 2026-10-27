"""Running external commands for actions: bounded, cancellable and killed as a whole process tree."""
from __future__ import annotations

import os
import subprocess
import threading

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


def run_command(command: str, timeout: float, stop: threading.Event, shell: bool = True) -> None:
    """Run `command` until it exits, `timeout` passes or `stop` is set; raises CommandFailed otherwise."""
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
    process = subprocess.Popen(command, shell=shell, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, creationflags=flags)
    waited = 0.0
    stderr = b''
    try:
        while True:
            try:
                _, stderr = process.communicate(timeout=POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                waited += POLL_SECONDS
                if stop.is_set():
                    raise CommandFailed('Stopped before the command finished') from None
                if waited >= timeout:
                    raise CommandFailed(f'The command did not finish within {timeout:g} seconds') from None
    finally:
        kill_tree(process)
    if process.returncode:
        tail = (stderr or b'').decode('utf-8', 'replace').strip()[-STDERR_TAIL:]
        raise CommandFailed(f'The command exited with code {process.returncode}' + (f': {tail}' if tail else ''))
