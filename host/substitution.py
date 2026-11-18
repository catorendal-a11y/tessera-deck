"""$(variable) substitution shared by the action engine and the editor's dry-run preview."""
from __future__ import annotations

import os
import re
import urllib.parse

# Only letters, digits and a few plain marks may go into a shell command: cmd.exe, POSIX shells and PowerShell
# (quotes, ( ) { } @ + and its typographic quotes) each have their own metacharacters, so list what is safe instead.
SHELL_UNSAFE = re.compile(r'[^\w .,:/-]')
# A value at the start of an argument that begins with / or - is read as an option (/p, --config); -5 is a number.
SHELL_SWITCH = re.compile(r'/|-(?!\d+(?:[.,]\d+)?$)')
ENV_REFERENCE = re.compile(r'[$][(]env:([A-Za-z_][A-Za-z0-9_]{0,63})[)]')
TOKEN = re.compile(r'[$][(]([^()]+)[)]')
UNSET_VARIABLE =re.compile(r'[$][(]var:[A-Za-z0-9_.-]+[)]')
# A counter or timer exists from its first use: until then a key shows where it starts, not the token itself.
UNUSED = {'counter': '0', 'timer': '00:00', 'timer-state': 'IDLE'}


def _shell_value(token: str, value: str, before: str) -> str:
    """`value` as one argument of a shell command whose text up to the token is `before`."""
    if SHELL_UNSAFE.search(value):
        raise ValueError(f'The value of {token} contains characters that are not allowed in a shell command')
    quoted = before.count('"') % 2 == 1
    # Inside double quotes only the text right after the opening quote starts an argument.
    starts_argument = before.endswith('"') if quoted else not before or before[-1].isspace()
    if starts_argument and SHELL_SWITCH.match(value):
        raise ValueError(f'The value of {token} starts with - or /, so a program would read it as an option')
    if ' ' in value and not quoted:
        return f'"{value}"'  # outside double quotes every space would start another argument
    return value


def substitute(text: str, variables: dict[str, str], mode: str | None = None) -> str:
    """Replace $(name) tokens. Mode 'shell' refuses values that could change a command and keeps a value with
    spaces one argument, 'url' percent-encodes.

    A custom variable nobody has set yet renders empty.
    """
    def replace(match):
        token, key = match.group(0), match.group(1)
        if key in variables:
            value = variables[key]
            if mode == 'shell':
                return _shell_value(token, value, text[:match.start()])
            return urllib.parse.quote(value, safe='') if mode == 'url' else value
        if UNSET_VARIABLE.fullmatch(token):
            return ''
        return UNUSED.get(key.partition(':')[0], token) if ':' in key and mode is None else token

    # One pass over the template: a substituted value is never scanned for further tokens.
    return TOKEN.sub(replace, text)


def check_web_url(url: str) -> str:
    """The address of an HTTP action must be http(s) with a host; anything else (file:, ftp:) is refused."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('The address must start with http:// or https://')
    return url


def expand_environment(text: str, environment=None) -> str:
    """Credentials live in the Windows environment, not in the profile: $(env:NAME)."""
    environment = os.environ if environment is None else environment
    return ENV_REFERENCE.sub(lambda match: environment.get(match.group(1), ''), text)
