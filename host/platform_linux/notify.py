"""Desktop notifications on Linux through `notify-send` (libnotify); a missing tool means no balloon, not an error."""
from __future__ import annotations

import shutil
import subprocess

BODY_MAX = 250  # characters of the message that reach notify-send; the rest is cut off


def notify(message: str, title: str = 'Tessera', run=subprocess.run) -> bool:
    """Show a notification; False when there is no notify-send or it failed."""
    if shutil.which('notify-send') is None:
        return False
    try:
        done = run(['notify-send', '--app-name=Tessera', '--', title[:80], message[:BODY_MAX]], timeout=3,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0
