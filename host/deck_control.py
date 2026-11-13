"""Lifecycle for the local Tessera USB host."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import psutil

from config_store import write_atomic

ROOT = Path(__file__).resolve().parents[1]
MAX_LOG_BYTES = 5 * 1024 * 1024
FIRMWARE_FLAG_PATH = ROOT / 'host/firmware-install.local.json'  # exists while the editor flashes the panel
FIRMWARE_FLAG_SECONDS = 600  # a flash takes about a minute; a flag left by a crashed editor expires


def firmware_installing(path=None):
    """True while the editor installs panel firmware: a host started then takes the COM port from esptool."""
    try:
        return time.time() - Path(path or FIRMWARE_FLAG_PATH).stat().st_mtime < FIRMWARE_FLAG_SECONDS
    except OSError:
        return False


def startup_script_path(appdata=None):
    """Return the per-user Windows Startup shortcut script."""
    base = Path(appdata or os.environ.get('APPDATA', ''))
    if not str(base):
        raise OSError('The Windows startup folder is not available')
    return base / 'Microsoft/Windows/Start Menu/Programs/Startup/Tessera.vbs'


def autostart_enabled(appdata=None):
    return os.name == 'nt' and startup_script_path(appdata).is_file()


def set_autostart(enabled, appdata=None):
    """Start the tray app (which starts the USB host) after the user signs in."""
    if os.name != 'nt' and appdata is None:
        raise OSError('Automatic startup is only supported on Windows')
    path = startup_script_path(appdata)
    if not enabled:
        path.unlink(missing_ok=True)
        return path
    pythonw = ROOT / 'host/.venv/Scripts/pythonw.exe'
    if not pythonw.is_file():
        raise OSError('Run Tessera.cmd once before enabling automatic startup')
    starter = ROOT / 'host/tessera_tray.py'
    command = f'"{pythonw}" "{starter}"'.replace('"', '""')
    contents = ('Set TesseraShell = CreateObject("WScript.Shell")\r\n'
                f'TesseraShell.Run "{command}", 0, False\r\n')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(contents, encoding='utf-16')  # Script Host reads a non-ASCII path only as UTF-16
    os.replace(temporary, path)
    return path


def save_profiles(config, path=None):
    from tesserad import validate_config
    validate_config(config)
    path = Path(path or ROOT / 'host/profiles.json')
    text = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
    # A unique, flushed temp file: the editor, terminal editor and tray can all save at once.
    write_atomic(path, text.encode('utf-8'))


class Controller:
    def __init__(self):
        self.pid_path = ROOT / 'host/deck-process.local.json'
        self.stop_path = ROOT / 'host/deck-stop.local.json'
        self.runtime_path = ROOT / 'host/deck-runtime.local.json'

    def processes(self, root=None):
        try:
            saved = json.loads(self.pid_path.read_text())
            # The editor asks every 1.5 s: a host already found is checked, not searched for again.
            known = getattr(self, 'known', None)
            if known and known[0] == (saved['pid'], saved['created']) and known[1].is_running():
                return [known[1]]
            process = psutil.Process(saved['pid'])
            command = process.cmdline()
            if (abs(process.create_time() - saved['created']) < .01 and len(command) > 1
                    and Path(command[1]).resolve() == ROOT / 'host/tesserad.py'):
                # Windows venv Python can keep a launcher process above the
                # interpreter. Track the actual daemon PID used by status/stop.
                matching = [process]
                for child in process.children(recursive=True):
                    arguments = child.cmdline()
                    if len(arguments) > 1 and Path(arguments[1]).resolve() == ROOT / 'host/tesserad.py':
                        matching.append(child)
                actual = matching[-1]
                if actual.pid != saved['pid']:
                    saved = {'pid': actual.pid, 'created': actual.create_time()}
                    self.pid_path.write_text(json.dumps(saved))
                self.known = ((saved['pid'], saved['created']), actual)
                return [actual]
        except (OSError, ValueError, KeyError, psutil.Error):
            pass
        return self.adopted()

    def adopted(self):
        """A host that was not started from here (a terminal, a script) still counts: it writes the runtime file.

        Without this the editor says "The host has stopped" while a host holds the USB port, and Start host
        launches a second one that exits at once.
        """
        try:
            process = psutil.Process(json.loads(self.runtime_path.read_text(encoding='utf-8'))['pid'])
            command = process.cmdline()
            if len(command) > 1 and Path(command[1]).resolve() == ROOT / 'host/tesserad.py':
                self.pid_path.write_text(json.dumps({'pid': process.pid, 'created': process.create_time()}))
                return [process]
        except (OSError, ValueError, KeyError, TypeError, psutil.Error):
            pass
        return []

    def status(self):
        processes = self.processes()
        result = {'running': bool(processes), 'connection': 'The host has stopped',
                  'device': {'connected': False, 'port': os.environ.get('TESSERA_PORT', 'COM4')}}
        if not processes:
            return result
        result['connection'] = 'Waiting for the panel'
        try:
            runtime = json.loads(self.runtime_path.read_text(encoding='utf-8'))
            if runtime.get('pid') != processes[0].pid or time.time() - float(runtime.get('updated', 0)) > 5:
                return result
            result['device'].update({key: runtime.get(key) for key in
                                     ('connected', 'port', 'profile', 'page', 'buttons', 'error',
                                      'foreground', 'auto_profile', 'last_action', 'firmware', 'protocol', 'layout_bytes', 'sensor_hint')})
            result['agents'] = runtime.get('agents', {})
            result['agent_states'] = runtime.get('agent_states', {})
            result['mixer'] = runtime.get('mixer', [])
            result['notices'] = runtime.get('notices', [])
            result['variables'] = runtime.get('variables', {})
            result['plugins'] = runtime.get('plugins', [])
            # Label previews in the editor resolve $(var:…) and $(stat:…) like the panel does.
            result['vars'] = runtime.get('vars', {})
            result['stats'] = runtime.get('stats', {})
            result['device']['gauges'] = runtime.get('gauges', {})
            result['connection'] = ('Panel connected' if runtime.get('connected')
                                    else runtime.get('error') or 'Waiting for the panel')
        except (OSError, ValueError, TypeError):
            pass
        return result

    def start(self, root=None, emit=lambda _: None):
        if firmware_installing():  # the tray, the terminal and the editor all start the host through here
            raise RuntimeError('The panel firmware is being installed. The host starts again when it is done.')
        if self.processes():
            emit('The deck host is already running.')
            return
        port = os.environ.get('TESSERA_PORT', 'COM4')
        from tesserad import Daemon
        Daemon.load_profiles(ROOT / 'host/profiles.json')
        log_path = ROOT / 'host/deck.local.log'
        try:  # the log is appended to on every start: keep one previous file instead of growing forever
            if log_path.stat().st_size > MAX_LOG_BYTES:
                os.replace(log_path, log_path.with_name('deck.local.log.1'))
        except OSError:
            pass
        log = log_path.open('ab')
        try:
            process = subprocess.Popen([sys.executable, str(ROOT / 'host/tesserad.py'), '--port', port],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                env=dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1'),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        finally:
            log.close()
        current = psutil.Process(process.pid)
        self.pid_path.write_text(json.dumps({'pid': process.pid, 'created': current.create_time()}))
        time.sleep(.3)
        if process.poll() is not None:
            raise RuntimeError('The host stopped right after it started. Open the host log (More → Host log) to see why.')
        self.processes()
        emit(f'The deck host has started on {port}.')

    def stop(self, root=None, emit=lambda _: None):
        processes = self.processes()
        for process in processes:
            self.stop_path.write_text(json.dumps({'pid': process.pid}))
        _, alive = psutil.wait_procs(processes, timeout=8)
        for process in alive:
            process.terminate()
        _, alive = psutil.wait_procs(alive, timeout=5)
        if alive:
            raise RuntimeError('Host did not stop; no new owner was started')
        self.stop_path.unlink(missing_ok=True)
        emit('The deck host has stopped. USB is released.')

    def install_adapters(self):
        return None
