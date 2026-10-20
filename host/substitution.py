"""$(variable) substitution shared by the action engine and the editor's dry-run preview."""
from __future__ import annotations

import os
import re
import urllib.parse

SHELL_UNSAFE = re.compile(r'[&|<>^"%;`$\r\n\\]')  # metacharacters of cmd.exe and POSIX shells
ENV_REFERENCE = re.compile(r'[$][(]env:([A-Za-z_][A-Za-z0-9_]{0,63})[)]')
UNSET_VARIABLE = re.compile(r'[$][(]var:[A-Za-z0-9_.-]+[)]')


def substitute(text: str, variables: dict[str, str], mode: str | None = None) -> str:
    """Replace $(name) tokens. Mode 'shell' refuses values that could change a command, 'url' percent-encodes.

    A custom variable nobody has set yet renders empty.
    """
    for key, value in variables.items():
        token = f'$({key})'
        if token not in text:
            continue
        if mode == 'shell' and SHELL_UNSAFE.search(value):
            raise ValueError(f'The value of {token} contains characters that are not allowed in a shell command')
        text = text.replace(token, urllib.parse.quote(value, safe='') if mode == 'url' else value)
    return UNSET_VARIABLE.sub('', text)


def expand_environment(text: str, environment=None) -> str:
    """Credentials live in the Windows environment, not in the profile: $(env:NAME)."""
    environment = os.environ if environment is None else environment
    return ENV_REFERENCE.sub(lambda match: environment.get(match.group(1), ''), text)
