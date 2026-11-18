"""Running script files on Linux: which interpreter a script type needs (the Windows side uses py.exe, cmd, AutoHotkey)."""
from __future__ import annotations

import os
import shutil
import sys

SUPPORTED = ('.py', '.pyw', '.sh', '.js', '.ps1')


def command(script: str, which=shutil.which) -> list[str]:
    """The argument list that runs `script`; ValueError names what is missing or not supported here."""
    suffix = os.path.splitext(script)[1].lower()
    if suffix not in SUPPORTED:
        raise ValueError(f'Script type {suffix or "(none)"} is not supported on Linux. Use {", ".join(SUPPORTED)}')
    if suffix in ('.py', '.pyw'):
        python = which('python3') or which('python') or sys.executable
        return [python, script]
    if suffix == '.sh':
        shell = which('bash') or which('sh')
        if not shell:
            raise ValueError('A shell (bash or sh) was not found')
        return [shell, script]
    if suffix == '.js':
        node = which('node') or which('nodejs')
        if not node:
            raise ValueError('Node.js (node) was not found on this PC')
        return [node, script]
    shell = which('pwsh')
    if not shell:
        raise ValueError('PowerShell (pwsh) was not found on this PC')
    return [shell, '-NoProfile', '-NonInteractive', '-File', script]
