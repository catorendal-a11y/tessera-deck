"""Plugin secrets at rest: settings named like a password are stored encrypted for the current Windows user.

Windows DPAPI ties the value to this user's login, so profiles.json and its backups hold "$(dpapi:<base64>)"
instead of the token. The plain value exists only in the plugin's environment. Elsewhere it stays plain text.
"""
from __future__ import annotations

import base64
import binascii
import os

from import_review import SECRET_SETTING

PREFIX, SUFFIX = '$(dpapi:', ')'
CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _dpapi(protect: bool, data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    crypt32, kernel32 = ctypes.WinDLL('crypt32', use_last_error=True), ctypes.WinDLL('kernel32')
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buffer = ctypes.create_string_buffer(data, len(data))
    source, target = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), Blob()
    if not function(ctypes.byref(source), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


def is_secret(name) -> bool:
    return isinstance(name, str) and bool(SECRET_SETTING.search(name))


def is_sealed(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX) and value.endswith(SUFFIX)


def protect(text: str) -> str:
    if os.name != 'nt' or not text or is_sealed(text):
        return text
    return PREFIX + base64.b64encode(_dpapi(True, text.encode('utf-8'))).decode('ascii') + SUFFIX


def unprotect(value):
    """The plain value; '' when it cannot be opened (another user or PC), so the plugin asks for it again."""
    if not is_sealed(value):
        return value
    if os.name != 'nt':
        return ''
    try:
        return _dpapi(False, base64.b64decode(value[len(PREFIX):-len(SUFFIX)], validate=True)).decode('utf-8')
    except (OSError, ValueError, binascii.Error):
        return ''


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
