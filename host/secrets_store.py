"""Plugin secrets at rest: settings named like a password are stored encrypted for the current user.

Windows DPAPI (platform_windows/secrets.py) ties the value to this user's login, so profiles.json and its backups
hold "$(dpapi:<base64>)" instead of the token. On Linux the value goes to the system keyring and the profile holds "$(keyring:<id>)"
(platform_linux/secrets.py). The plain value exists only in the plugin's environment.
"""
from __future__ import annotations

from import_review import SECRET_SETTING
from platform_support import load

PREFIX, SUFFIX = '$(dpapi:', ')'
KEYRING_PREFIX = '$(keyring:'


def is_secret(name) -> bool:
    return isinstance(name, str) and bool(SECRET_SETTING.search(name))


def is_sealed(value) -> bool:
    return isinstance(value, str) and value.endswith(SUFFIX) and value.startswith((PREFIX, KEYRING_PREFIX))


def protect(text: str) -> str:
    """`text` in its sealed form for this system (Windows DPAPI, Linux keyring); an empty or sealed value stays as it is."""
    if not text or is_sealed(text):
        return text
    return load('secrets').seal(text)


def unprotect(value):
    """The plain value; '' when it cannot be opened (another user or PC, or sealed on the other system), so the plugin
    asks for it again."""
    if not is_sealed(value):
        return value
    return load('secrets').unseal(value)


def seal_plugins(config: dict, previous: dict | None = None) -> dict:
    """A copy of `config` whose secret plugin settings are encrypted. DPAPI output differs every time, so a value
    that did not change keeps the blob already saved: the file stays the same and the plugin is not restarted."""
    block = config.get('plugins') if isinstance(config, dict) else None
    if not isinstance(block, dict):
        return config
    old = (previous or {}).get('plugins') if isinstance(previous, dict) else None
    old = old if isinstance(old, dict) else {}
    plugins = {}
    for plugin_id, entry in block.items():
        settings = entry.get('settings') if isinstance(entry, dict) else None
        if not isinstance(settings, dict):
            plugins[plugin_id] = entry
            continue
        saved = (old.get(plugin_id) or {}).get('settings') if isinstance(old.get(plugin_id), dict) else None
        saved = saved if isinstance(saved, dict) else {}
        sealed = {}
        for key, value in settings.items():
            if is_secret(key) and isinstance(value, str) and value and not is_sealed(value):
                kept = saved.get(key)
                value = kept if is_sealed(kept) and unprotect(kept) == value else protect(value)
            sealed[key] = value
        plugins[plugin_id] = dict(entry, settings=sealed)
    return dict(config, plugins=plugins)


def open_settings(settings: dict) -> dict:
    """The settings a plugin is started with, secrets decrypted."""
    return {key: unprotect(value) for key, value in settings.items()}
