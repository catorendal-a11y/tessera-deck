"""Single-instance lock and serial-number port pinning for the USB host."""
import contextlib
import json
import os
from pathlib import Path
import threading

from platform_support import IS_LINUX, load

ESPRESSIF_VID = 0x303A  # USB Serial/JTAG of the ESP32-P4 and of the native-USB S3 board
CH340_VID = 0x1A86  # the UART bridge of the ESP32-8048S070 and the CrowPanel boards
PANEL_VIDS = (ESPRESSIF_VID, CH340_VID)
UART_BAUD = 921600  # firmware UART speed on the CH340 board; USB Serial/JTAG ignores the baud rate
DEFAULT_BAUD = 115200
DEFAULT_PORT = load('labels').DEFAULT_PORT  # Linux has no fixed port name: the panel is found by its USB id
PIN_FILE = 'deck-port.local.json'  # {"port": ...}: the one port to use, set in the editor
PORT_EXAMPLE = '/dev/ttyUSB0' if IS_LINUX else 'COM7'


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


def filelock():
    """The file-lock module of this system."""
    if IS_LINUX:
        from platform_linux import filelock as module
    else:
        from platform_windows import filelock as module
    return module


class InstanceLock:
    """OS-level exclusive lock; released automatically when the process dies."""

    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def acquire(self):
        handle = open(self.path, 'a+')
        try:
            filelock().lock(handle)
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
            filelock().unlock(self.handle)
        except OSError:
            pass
        finally:
            self.handle.close()
            self.handle = None


def session_locked() -> bool:
    """True while the lock screen has the input (Windows: the secure desktop; Linux: logind and the screensaver)."""
    if IS_LINUX:
        from platform_linux import session
    else:
        from platform_windows import session
    return session.locked()


def pc_idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input on this PC; infinity where the system cannot tell."""
    return load('session').idle_seconds()


def _installed_ports():
    from serial.tools import list_ports
    return {port.device: port.serial_number for port in list_ports.comports()}



def _espressif_ports():
    from serial.tools import list_ports
    return [port.device for port in list_ports.comports() if port.vid in PANEL_VIDS]


def device_name(port):
    """The name the port list has for `port`: on Linux a pinned port may be a link such as /dev/serial/by-id/..."""
    return os.path.realpath(port) if IS_LINUX and port.startswith('/') else port


def port_baud(port):
    try:
        from serial.tools import list_ports
        device = device_name(port)
        uart = any(item.device == device and item.vid == CH340_VID for item in list_ports.comports())
    except Exception:  # no pyserial tools, or a driver that cannot be listed: the USB default works for the P4
        uart = False
    return UART_BAUD if uart else DEFAULT_BAUD


def port_name(value):
    """A port as the user wrote it, in the system's spelling (com7 is COM7); None when it cannot be a port's name."""
    value = value.strip() if isinstance(value, str) else ''
    if IS_LINUX:
        return value if value.startswith('/dev/') and len(value) > 5 else None
    return value.upper() if value[:3].upper() == 'COM' and value[3:].isdigit() else None


def pinned_port(folder):
    """The one port the user told Tessera to use, or None. With it no other port is opened and none is looked for.

    The environment variable TESSERA_PORT wins over the port kept in deck-port.local.json in `folder` (the editor
    writes that file). The file is read each time, so a change counts at the host's next attempt to connect.
    """
    named = os.environ.get('TESSERA_PORT', '').strip()
    if named:
        return port_name(named) or named  # the variable is taken as it is: it was the only way before, for any name
    return stored_pin(folder)


def stored_pin(folder):
    """The port kept in deck-port.local.json, whatever TESSERA_PORT says."""
    return port_name(_remembered(Path(folder) / PIN_FILE, 'port'))


def pin_port(folder, port):
    """Keep `port` as the only port to use; an empty `port` lets Tessera find the panel by itself again."""
    path = Path(folder) / PIN_FILE
    if not port:
        path.unlink(missing_ok=True)
        return None
    name = port_name(port)
    if not name:
        raise ValueError(f'{port!r} is not a port name. Write it like {PORT_EXAMPLE}.')
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'port': name}), encoding='utf-8')
    os.replace(temporary, path)
    return name


def candidate_ports(requested, state_path, installed=None, espressif=None):
    """Ports to try, best first: the remembered/requested port, then other Espressif and CH340 USB devices.

    Every candidate is verified with a handshake before it is configured, so a second ESP32 is never configured. It is
    still opened to ask, which restarts a UART board on Linux; the host's open_panel asks such a device only a few times.
    A pinned port (pinned_port) never comes here: its callers use that port alone.
    """
    first = resolve_port(requested, state_path, installed)
    try:
        others = espressif if espressif is not None else _espressif_ports()
    except (ImportError, OSError):
        return [first] if first else []
    # The port name (COM4 on Windows) is a guess: it is tried only when a panel's USB id is on it, so a modem or
    # Bluetooth port there is never opened and its errors never hide what the real panel said.
    if first not in others:
        first = None
    return ([first] if first else []) + [device for device in sorted(others) if device != first]


def _remembered(state_path, key):
    try:
        value = json.loads(Path(state_path).read_text(encoding='utf-8')).get(key)
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and value else None


def remembered_serial(state_path):
    return _remembered(state_path, 'serial')


def resolve_port(requested, state_path, installed=None):
    """Follow the panel when Windows renumbers its COM port.

    Only a port whose USB serial number matches the remembered panel is chosen.
    Other boards (for example a second ESP32 on another port) are never chosen here.
    """
    serial = remembered_serial(state_path)
    named = _remembered(state_path, 'port')  # a CH340 bridge often has no serial number: its port name is remembered
    if not serial and not named:
        return requested
    try:
        ports = installed if installed is not None else _installed_ports()
    except (ImportError, OSError):
        return requested
    if not serial:
        return named if named in ports else requested
    if ports.get(requested) == serial:
        return requested
    return next((device for device, number in sorted(ports.items()) if number == serial), requested)


def is_remembered_panel(port, state_path, installed):
    """True when `port` holds the panel this host connected to before (by serial number, or by name without one)."""
    serial = remembered_serial(state_path)
    return installed.get(port) == serial if serial else port == _remembered(state_path, 'port')


def remember_port(port, state_path, installed=None):
    """Store the serial number of the port we connected to, or the port name when it has none."""
    try:
        ports = installed if installed is not None else _installed_ports()
    except (ImportError, OSError):
        return
    if port not in ports:
        return
    serial = ports[port]
    if serial:
        if serial == remembered_serial(state_path):
            return
        state = {'serial': serial}
    else:
        if port == _remembered(state_path, 'port') and not remembered_serial(state_path):
            return
        state = {'port': port}
    temporary = Path(state_path).with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(state), encoding='utf-8')
        os.replace(temporary, state_path)
    except OSError:
        pass
