"""Plugin secrets in the system keyring (the freedesktop Secret Service: GNOME Keyring, KWallet, KeePassXC ...).

A profile keeps `$(keyring:<id>)`; the value itself lives in the keyring under that id, so profiles.json and its
backups never hold it. Nothing is written in plain text when the keyring is missing or locked: the call fails.
"""
from __future__ import annotations

import secrets

SERVICE = 'tessera-deck plugin secret'


def _keyring():
    try:
        import keyring
        from keyring.backends import fail
    except ImportError as exc:
        raise OSError('Secrets need the "keyring" Python package: run Tessera.sh once to install it') from exc
    if isinstance(keyring.get_keyring(), fail.Keyring):
        raise OSError('No system keyring was found: start GNOME Keyring, KWallet or another Secret Service')
    return keyring


def store(value: str) -> str:
    """Put `value` in the keyring and return the id to keep in the profile."""
    keyring = _keyring()
    identifier = secrets.token_urlsafe(12)
    try:
        keyring.set_password(SERVICE, identifier, value)
    except Exception as exc:  # keyring raises its own error classes (locked, denied, no service)
        raise OSError(f'The system keyring refused the secret: {exc}') from exc
    return identifier


def fetch(identifier: str) -> str | None:
    """The stored value, or None when the keyring does not have it (another user or PC, or it was deleted)."""
    keyring = _keyring()
    try:
        return keyring.get_password(SERVICE, identifier)
    except Exception as exc:
        raise OSError(f'The system keyring could not be read: {exc}') from exc


def forget(identifier: str) -> None:
    try:
        _keyring().delete_password(SERVICE, identifier)
    except Exception:  # already gone, or not reachable: nothing to clean up
        pass


def seal(text: str) -> str:
    """The profile's `$(keyring:<id>)` form of `text`; OSError when there is no usable keyring."""
    from secrets_store import KEYRING_PREFIX, SUFFIX
    return KEYRING_PREFIX + store(text) + SUFFIX


def unseal(value: str) -> str:
    """The plain text of a `$(keyring:<id>)` value; '' for anything else or one the keyring cannot give."""
    from secrets_store import KEYRING_PREFIX, SUFFIX
    if not value.startswith(KEYRING_PREFIX):
        return ''
    try:
        return fetch(value[len(KEYRING_PREFIX):-len(SUFFIX)]) or ''
    except OSError:
        return ''
