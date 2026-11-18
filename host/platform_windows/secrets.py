"""Plugin secrets on Windows: sealed with DPAPI for the current user (the value only opens for this login on this PC)."""
from __future__ import annotations

CRYPTPROTECT_UI_FORBIDDEN = 0x1


def dpapi(protect: bool, data: bytes) -> bytes:
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


def seal(text: str) -> str:
    """The profile's `$(dpapi:...)` form of `text`. Where there is no DPAPI (a development machine that is not Windows) the text stays as it is."""
    import os
    if os.name != 'nt':
        return text
    import base64
    from secrets_store import PREFIX, SUFFIX
    return PREFIX + base64.b64encode(dpapi(True, text.encode('utf-8'))).decode('ascii') + SUFFIX


def unseal(value: str) -> str:
    """The plain text of a `$(dpapi:...)` value; '' for anything else or one that does not open (another user or PC)."""
    import base64
    import binascii
    from secrets_store import PREFIX, SUFFIX
    import os
    if os.name != 'nt' or not value.startswith(PREFIX):
        return ''  # a sealed value never opens without DPAPI, and is never handed on as the secret
    try:
        return dpapi(False, base64.b64decode(value[len(PREFIX):-len(SUFFIX)], validate=True)).decode('utf-8')
    except (OSError, ValueError, binascii.Error):
        return ''
