"""Lifecycle for the local Agent Deck USB host."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import psutil

ROOT = Path(__file__).resolve().parents[1]


def startup_script_path(appdata=None):
    """Return the per-user Windows Startup shortcut script."""
    base = Path(appdata or os.environ.get('APPDATA', ''))
    if not str(base):
        raise OSError('Windows sin oppstartsmappe er ikke tilgjengelig')
    return base / 'Microsoft/Windows/Start Menu/Programs/Startup/Agent Deck Host.vbs'


def autostart_enabled(appdata=None):
    return os.name == 'nt' and startup_script_path(appdata).is_file()


def set_autostart(enabled, appdata=None):
    """Start only the background USB host after the user signs in."""
    if os.name != 'nt' and appdata is None:
        raise OSError('Automatisk oppstart støttes bare på Windows')
    path = startup_script_path(appdata)
    if not enabled:
        path.unlink(missing_ok=True)
        return path
    pythonw = ROOT / 'host/.venv/Scripts/pythonw.exe'
    if not pythonw.is_file():
        raise OSError('Kjør Agent-Deck.cmd én gang før automatisk oppstart aktiveres')
    starter = ROOT / 'host/start_host.py'
    command = f'"{pythonw}" "{starter}"'.replace('"', '""')
    contents = ('Set AgentDeckShell = CreateObject("WScript.Shell")\r\n'
                f'AgentDeckShell.Run "{command}", 0, False\r\n')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(contents, encoding='utf-8')
    os.replace(temporary, path)
    return path


def configure_upstream():
    """Compatibility no-op for launchers created before Deck became standalone."""


def save_profiles(config, path=None):
    from agent_deckd import validate_config
    validate_config(config)
    path = Path(path or ROOT / 'host/profiles.json')
    text = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(text, encoding='utf-8')
    os.replace(temporary, path)


class Controller:
    def __init__(self):
        self.pid_path = ROOT / 'host/deck-process.local.json'
        self.stop_path = ROOT / 'host/deck-stop.local.json'
        self.runtime_path = ROOT / 'host/deck-runtime.local.json'

    def processes(self, root=None):
        try:
            saved = json.loads(self.pid_path.read_text())
            process = psutil.Process(saved['pid'])
            command = process.cmdline()
            if (abs(process.create_time() - saved['created']) < .01 and len(command) > 1
                    and Path(command[1]).resolve() == ROOT / 'host/agent_deckd.py'):
                # Windows venv Python can keep a launcher process above the
                # interpreter. Track the actual daemon PID used by status/stop.
                matching = [process]
                for child in process.children(recursive=True):
                    arguments = child.cmdline()
                    if len(arguments) > 1 and Path(arguments[1]).resolve() == ROOT / 'host/agent_deckd.py':
                        matching.append(child)
                actual = matching[-1]
                if actual.pid != saved['pid']:
                    self.pid_path.write_text(json.dumps({'pid': actual.pid, 'created': actual.create_time()}))
                return [actual]
        except (OSError, ValueError, KeyError, psutil.Error):
            pass
        return []

    def status(self):
        processes = self.processes()
        result = {'running': bool(processes), 'connection': 'Verten er stoppet',
                  'device': {'connected': False, 'port': os.environ.get('AGENT_DECK_PORT', 'COM4')}}
        if not processes:
            return result
        result['connection'] = 'Venter på enheten'
        try:
            runtime = json.loads(self.runtime_path.read_text(encoding='utf-8'))
            if runtime.get('pid') != processes[0].pid or time.time() - float(runtime.get('updated', 0)) > 5:
                return result
            result['device'].update({key: runtime.get(key) for key in
                                     ('connected', 'port', 'profile', 'page', 'buttons', 'error',
                                      'foreground', 'auto_profile', 'last_action')})
            result['agents'] = runtime.get('agents', {})
            result['connection'] = ('Panel tilkoblet' if runtime.get('connected')
                                    else runtime.get('error') or 'Venter på enheten')
        except (OSError, ValueError, TypeError):
            pass
        return result

    def start(self, root=None, emit=lambda _: None):
        if self.processes():
            emit('Deck-verten kjører allerede.')
            return
        port = os.environ.get('AGENT_DECK_PORT', 'COM4')
        from agent_deckd import Daemon
        Daemon.load_profiles(ROOT / 'host/profiles.json')
        log = (ROOT / 'host/deck.local.log').open('ab')
        try:
            process = subprocess.Popen([sys.executable, str(ROOT / 'host/agent_deckd.py'), '--port', port],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                env=dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1'),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        finally:
            log.close()
        current = psutil.Process(process.pid)
        self.pid_path.write_text(json.dumps({'pid': process.pid, 'created': current.create_time()}))
        time.sleep(.3)
        if process.poll() is not None:
            raise RuntimeError('Host failed to start; open the Deck log')
        self.processes()
        emit(f'Deck-verten er startet på {port}.')

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
        emit('Deck-verten er stoppet. USB er frigitt.')

    def install_adapters(self):
        return None


def firmware_files(kind):
    build = ROOT / 'build/idf6'
    files = [(0x10000, build / 'agent_deck.bin')]
    if kind == 'install':
        files = [(0x2000, build / 'bootloader/bootloader.bin'),
                 (0x8000, build / 'partition_table/partition-table.bin')] + files
    if any(not path.is_file() for _, path in files):
        raise ValueError('Build the Agent Deck firmware first')
    return [(offset, path, hashlib.sha256(path.read_bytes()).hexdigest()) for offset, path in files]


