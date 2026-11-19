"""The D-Bus that KDE Connect starts for itself on Windows. What a call does is shared (host/dbus_client.py); here is only how
that bus is found and joined.

KDE Connect for Windows (Microsoft Store or kde.org) brings its own `dbus-daemon.exe` next to `kdeconnectd.exe`. The daemon
listens on a TCP port of 127.0.0.1 (`autolaunch:scope=*install-path`) and publishes its address in a named shared memory
block, `DBusDaemonAddressInfo-` plus the SHA-1 of its install folder, as libdbus does when a client autolaunches. The host
finds the running daemon, reads that address (or, failing that, the port the daemon listens on), and signs in with EXTERNAL:
the daemon looks up which process owns the client's TCP connection and accepts it when that runs as the same Windows user,
whose SID is the identity sent. Nothing is started: without KDE Connect running there is simply no bus.
"""
from __future__ import annotations

import binascii
import hashlib
import os
import socket

from dbus_client import TIMEOUT, Bus

DAEMON = 'dbus-daemon.exe'
KDECONNECT = 'kdeconnectd.exe'  # a dbus-daemon of another KDE program is not the one
ADDRESS_INFO = 'DBusDaemonAddressInfo-'
FILE_MAP_READ = 0x0004


def daemon_roots() -> list[tuple[str, int]]:
    """(install folder, process id) of each running dbus-daemon that came with KDE Connect."""
    import psutil
    found = []
    for process in psutil.process_iter(['name']):
        if (process.info.get('name') or '').lower() != DAEMON:
            continue
        try:
            folder = os.path.dirname(process.exe())
        except (psutil.Error, OSError):
            continue
        if os.path.exists(os.path.join(folder, KDECONNECT)):
            found.append((os.path.dirname(folder), process.pid))
    return found


def address_name(root: str) -> str:
    """The shared memory name libdbus gives the address of a daemon in `root`: the install folder with a closing backslash,
    ASCII letters in lower case, as SHA-1."""
    folder = root.rstrip('\\/') + '\\'
    lowered = ''.join(char.lower() if char.isascii() else char for char in folder)
    return ADDRESS_INFO + hashlib.sha1(lowered.encode('mbcs', errors='replace')).hexdigest()


def read_shared_text(name: str) -> str | None:
    """The text a named shared memory block holds, or None when there is none."""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenFileMappingW.restype = wintypes.HANDLE
    kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    kernel32.MapViewOfFile.restype = ctypes.c_void_p
    kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenFileMappingW(FILE_MAP_READ, False, name)
    if not handle:
        return None
    try:
        view = kernel32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 0)
        if not view:
            return None
        try:
            return ctypes.string_at(view).decode('ascii', errors='replace')
        finally:
            kernel32.UnmapViewOfFile(view)
    finally:
        kernel32.CloseHandle(handle)


def tcp_endpoint(address: str) -> tuple[str, int] | None:
    """(host, port) of the first `tcp:` entry of a D-Bus address, or None when it has none."""
    for entry in address.split(';'):
        kind, _, options = entry.strip().partition(':')
        if kind != 'tcp':
            continue
        values = dict(part.partition('=')[::2] for part in options.split(',') if part)
        if values.get('port', '').isdigit():
            host = values.get('host') or 'localhost'
            return ('127.0.0.1' if host == 'localhost' and values.get('family', 'ipv4') == 'ipv4' else host), int(values['port'])
    return None


def listening_port(pid: int) -> int | None:
    """The port the process listens on at 127.0.0.1, when the shared memory block cannot be read."""
    import psutil
    try:
        for connection in psutil.Process(pid).net_connections('tcp'):
            if connection.status == psutil.CONN_LISTEN and connection.laddr and connection.laddr.ip == '127.0.0.1':
                return connection.laddr.port
    except (psutil.Error, OSError):
        return None
    return None


def find_endpoint() -> tuple[str, int]:
    """Where KDE Connect's bus is reached; OSError when KDE Connect is not running."""
    for root, pid in daemon_roots():
        endpoint = tcp_endpoint(read_shared_text(address_name(root)) or '')
        if endpoint is None:
            port = listening_port(pid)
            endpoint = ('127.0.0.1', port) if port else None
        if endpoint is not None:
            return endpoint
    raise OSError('KDE Connect is not running')


def user_sid() -> str:
    """The SID of the user this process runs as (S-1-5-21-...): the identity of an EXTERNAL sign-in on Windows."""
    import win32api
    import win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    try:
        return win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token, win32security.TokenUser)[0])
    finally:
        token.Close()


def _read_line(sock: socket.socket) -> bytes:
    line = b''
    while not line.endswith(b'\r\n'):
        chunk = sock.recv(1)
        if not chunk:
            raise OSError('KDE Connect closed the connection while signing in')
        line += chunk
        if len(line) > 4096:
            raise OSError('KDE Connect sent an unexpected answer while signing in')
    return line


def authenticate(sock: socket.socket, sid: str) -> None:
    """The SASL exchange before any message: a null byte, AUTH EXTERNAL with the hex of the SID, then BEGIN after OK."""
    sock.sendall(b'\0AUTH EXTERNAL ' + binascii.hexlify(sid.encode('ascii')) + b'\r\n')
    answer = _read_line(sock)
    if not answer.startswith(b'OK '):
        raise OSError(f'KDE Connect refused the sign-in: {answer.strip().decode("ascii", errors="replace")}')
    sock.sendall(b'BEGIN\r\n')


class KdeConnectBus(Bus):
    """The bus of the running KDE Connect. Each connection looks the daemon up again, so a restarted KDE Connect (a new
    port) is found on the next call after the back-off."""

    def __init__(self, timeout: float = TIMEOUT):
        super().__init__(timeout)

    def _open(self):
        from jeepney.io.blocking import DBusConnection
        host, port = find_endpoint()
        sock = socket.create_connection((host, port), timeout=self.timeout)
        try:
            authenticate(sock, user_sid())
            return DBusConnection(sock)  # says Hello; the socket keeps its timeout, so a silent daemon cannot hang it
        except Exception as exc:
            sock.close()
            if isinstance(exc, OSError):
                raise
            raise OSError(f'KDE Connect: {exc}') from exc
