"""Running the command line tools the Linux backends use (xdotool, xclip, wl-copy). A missing tool is reported with the
package to install."""
from __future__ import annotations

import shutil
import subprocess

from platform_linux import BackendUnavailable

TIMEOUT = 5.0
HINT = {'xdotool': 'xdotool', 'xclip': 'xclip', 'wl-copy': 'wl-clipboard', 'wl-paste': 'wl-clipboard'}


def run(args: list[str], stdin: str | None = None, timeout: float = TIMEOUT, detach: bool = False) -> str:
    """Run a tool and return its output. Raises BackendUnavailable when the tool is missing, OSError when it fails.

    `detach`: the tool leaves a background process behind (xclip serving the clipboard), which would keep a pipe
    open for good, so its output is not captured."""
    if shutil.which(args[0]) is None:
        raise BackendUnavailable(f'{args[0]} is not installed: install the "{HINT.get(args[0], args[0])}" package')
    try:
        if detach:
            done = subprocess.run(args, input=stdin, text=True, timeout=timeout, check=False,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            done.stdout = done.stderr = ''
        else:
            done = subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise OSError(f'{args[0]} did not answer within {timeout:g} seconds') from exc
    if done.returncode != 0:
        raise OSError(f'{args[0]} failed: {(done.stderr or "").strip()[:200] or done.returncode}')
    return done.stdout
