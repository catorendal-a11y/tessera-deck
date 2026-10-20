"""Single-instance lock and serial-number port pinning for the USB host."""
import contextlib
import json
import os
from pathlib import Path
import threading


class SuspendableRLock:
    """A re-entrant lock that can be fully released around a blocking call and re-taken afterwards.

    Actions that wait (shell, HTTP, delays) must not keep the host's state locked, otherwise the
    panel, focus tracking and the control API stall behind them.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._owner = None
        self._count = 0

    def acquire(self, blocking=True, timeout=-1):
        me = threading.get_ident()
        if self._owner == me:
            self._count += 1
            return True
        if not self._lock.acquire(blocking, timeout):
            return False
        self._owner, self._count = me, 1
        return True

    def release(self):
        if self._owner != threading.get_ident():
            raise RuntimeError('release of a lock the thread does not hold')
        self._count -= 1
        if self._count == 0:
            self._owner = None
            self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()

    @contextlib.contextmanager
    def suspended(self):
        """Fully release the lock for the duration of the block (no-op when this thread does not hold it)."""
        if self._owner != threading.get_ident():
            yield
            return
        saved = self._count
        self._owner, self._count = None, 0
        self._lock.release()
        try:
            yield
        finally:
            self._lock.acquire()
            self._owner, self._count = threading.get_ident(), saved


class InstanceLock:
    """OS-level exclusive lock; released automatically when the process dies."""

    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def acquire(self):
        handle = open(self.path, 'a+')
        try:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self.handle = handle
        return True

    def release(self):
        if self.handle is None:
            return
        try:
            if os.name == 'nt':
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            self.handle.close()
            self.handle = None


def session_locked() -> bool:
    """True while the Windows lock screen (the secure desktop) has the input."""
    if os.name != 'nt':
        return False
    import ctypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.OpenInputDesktop.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    user32.OpenInputDesktop.restype = ctypes.c_void_p
    user32.CloseDesktop.argtypes = [ctypes.c_void_p]
    desktop = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
    if not desktop:
        return True
    user32.CloseDesktop(desktop)
    return False


def _installed_ports():
    from serial.tools import list_ports
    return {port.device: port.serial_number for port in list_ports.comports()}


ESPRESSIF_VID = 0x303A  # USB Serial/JTAG of the ESP32-P4


def _espressif_ports():
    from serial.tools import list_ports
    return [port.device for port in list_ports.comports() if port.vid == ESPRESSIF_VID]


def candidate_ports(requested, state_path, installed=None, espressif=None):
    """Ports to try, best first: the remembered/requested port, then other Espressif USB devices.

    Every candidate is verified with a handshake before it is configured, so a second ESP32 is never touched.
    """
    first = resolve_port(requested, state_path, installed)
    try:
        others = espressif if espressif is not None else _espressif_ports()
    except (ImportError, OSError):
        others = []
    return [first] + [device for device in sorted(others) if device != first]


def remembered_serial(state_path):
    try:
        value = json.loads(Path(state_path).read_text(encoding='utf-8')).get('serial')
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and value else None


def resolve_port(requested, state_path, installed=None):
    """Follow the panel when Windows renumbers its COM port.

    Only a port whose USB serial number matches the remembered panel is chosen.
    Other boards (for example a second ESP32 on another port) are never touched.
    """
    serial = remembered_serial(state_path)
    if not serial:
        return requested
    try:
        ports = installed if installed is not None else _installed_ports()
    except (ImportError, OSError):
        return requested
    if ports.get(requested) == serial:
        return requested
    return next((device for device, number in sorted(ports.items()) if number == serial), requested)


def remember_port(port, state_path, installed=None):
    """Store the serial number of the port we connected to; no-op if unknown."""
    try:
        serial = (installed if installed is not None else _installed_ports()).get(port)
    except (ImportError, OSError):
        return
    if not serial or serial == remembered_serial(state_path):
        return
    temporary = Path(state_path).with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps({'serial': serial}), encoding='utf-8')
        os.replace(temporary, state_path)
    except OSError:
        pass
