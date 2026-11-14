"""$(variable) substitution shared by the action engine and the editor's dry-run preview."""
from __future__ import annotations

import os
import re
import urllib.error
import urllib.parse
import urllib.request

SHELL_UNSAFE = re.compile(r'[&|<>^"%;`$\r\n\\]')  # metacharacters of cmd.exe and POSIX shells
ENV_REFERENCE = re.compile(r'[$][(]env:([A-Za-z_][A-Za-z0-9_]{0,63})[)]')
TOKEN = re.compile(r'[$][(]([^()]+)[)]')
UNSET_VARIABLE =re.compile(r'[$][(]var:[A-Za-z0-9_.-]+[)]')


def substitute(text: str, variables: dict[str, str], mode: str | None = None, environment=None) -> str:
    """Replace $(name) tokens. Mode 'shell' refuses values that could change a command, 'url' percent-encodes.

    A custom variable nobody has set yet renders empty. With `environment` given, $(env:NAME) is resolved in
    the same pass, so a variable whose value looks like $(env:NAME) is never expanded into a credential.
    """
    def replace(match):
        token, key = match.group(0), match.group(1)
        if environment is not None and ENV_REFERENCE.fullmatch(token):
            return environment.get(key[4:], '')  # the user's own credentials and addresses: never encoded
        if key in variables:
            value = variables[key]
            if mode == 'shell' and SHELL_UNSAFE.search(value):
                raise ValueError(f'The value of {token} contains characters that are not allowed in a shell command')
            return urllib.parse.quote(value, safe='') if mode == 'url' else value
        return '' if UNSET_VARIABLE.fullmatch(token) else token

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


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to the same host and never from https to http.

    urllib copies every header (Authorization, $(env:TOKEN) headers) to the redirect target, so a redirect
    to another host would hand the credentials over.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlparse(req.full_url), urllib.parse.urlparse(newurl)
        if new.scheme not in ('http', 'https') or (old.scheme == 'https' and new.scheme != 'https') \
                or (old.hostname or '').lower() != (new.hostname or '').lower():
            raise urllib.error.HTTPError(req.full_url, code, 'Redirect to another host or to plain http refused', headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(request, timeout):
    """urlopen for HTTP actions with the redirect rule above."""
    return urllib.request.build_opener(_SameHostRedirects).open(request, timeout=timeout)
