"""Local graphical editor for the standalone Tessera."""
import logging
import argparse
import copy
import hashlib
from functools import lru_cache
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.parse
import webbrowser

from deck_control import (FIRMWARE_FLAG_PATH, ROOT, Controller, autostart_enabled,
                          save_profiles, set_autostart)
from tesserad import SUPPORTED_PROTOCOLS, Daemon, DeviceRejected, PanelSerial, bring_to_front, validate_config
from deck_assets import Assets
import ambient
import config_store
import diagnostics
import firmware_update
import iconify
import plugins
import updates
from host_runtime import InstanceLock
from action_preview import preview
from import_review import redact_secrets, review, strip_executable

WEB = Path(__file__).with_name('editor')


def editor_build_id():
    """Fingerprint every file cached or imported by the long-lived editor."""
    digest = hashlib.sha256()
    files = [Path(__file__), ROOT / 'host/deck_control.py', ROOT / 'host/deck_assets.py',
             ROOT / 'host/tesserad.py', ROOT / 'host/config_check.py', ROOT / 'host/panel_serial.py',
             ROOT / 'host/win_input.py', ROOT / 'host/action_packs.json',
             WEB / 'index.html', WEB / 'style.css', WEB / 'cockpit.css', WEB / 'core.js', WEB / 'app.js', WEB / 'dialogs.js']
    for path in files:
        digest.update(path.name.encode('utf-8'))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def activate_window(pid):
    """Restore the existing native editor instead of opening a duplicate."""
    if os.name != 'nt':
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        found = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def visit(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                title = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title, length + 1)
                if title.value == 'Tessera':
                    found.append(hwnd)
                    return False
            return True

        user32.EnumWindows(visit, 0)
        if not found:
            return False
        bring_to_front(user32, found[0])
        return True
    except (AttributeError, OSError, ValueError):
        return False


@lru_cache(maxsize=1)
def icon_catalog():
    return json.loads((ROOT / 'vendor/lucide/catalog.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def icon_ids():
    return frozenset(item['id'] for item in icon_catalog()['icons'])


@lru_cache(maxsize=1)
def action_pack_catalog():
    catalog = json.loads((ROOT / 'host/action_packs.json').read_text(encoding='utf-8'))
    if catalog.get('version') != 1 or not isinstance(catalog.get('packs'), list) or not isinstance(catalog.get('templates'), list):
        raise ValueError('Invalid action pack')
    for index, pack in enumerate(catalog['packs'], 1):
        profile = {'match': [], 'pages': {'main': [{
            'id': 1, 'label': pack.get('name', ''), 'icon': pack.get('icon', 'ok'),
            'color': pack.get('color', '#35D07F'), 'actions': pack.get('actions', [])}]}}
        validate_config({'default_profile': 'pakke', 'profiles': {'pakke': profile}})
        pack['id'] = f'pack-{index}'
    for template in catalog['templates']:
        if not isinstance(template.get('description'), str):
            raise ValueError('The profile template needs a description')
        validate_config({'default_profile': template.get('name'),
                         'profiles': {template.get('name'): template.get('profile')}})
    for template in catalog.get('page_templates', []):
        if not isinstance(template.get('name'), str) or not isinstance(template.get('description'), str):
            raise ValueError('The page template needs a name and a description')
        validate_config({'default_profile': 'mal', 'profiles': {'mal': {'match': [], 'pages': {'side': template.get('page')}}}})
    return catalog


APP_USER_MODEL_ID = 'Tessera.Editor'


def brand_taskbar_identity():
    """Give this process its own Windows identity.

    Without one, Windows groups the editor window under pythonw.exe and shows the Python
    file icon on the taskbar instead of the window's own icon.
    """
    if os.name != 'nt':
        return
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def fit_to_work_area(window):
    """Fill the screen without covering the taskbar: a maximized WebView2 window can end up under it."""
    try:
        import ctypes
        from ctypes import wintypes
        window.events.shown.wait(15)
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        area = wintypes.RECT()
        if not user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0):  # SPI_GETWORKAREA: the screen minus the taskbar
            return
        handle = user32.FindWindowW(None, 'Tessera')
        if handle:
            user32.ShowWindow(handle, 9)  # SW_RESTORE, so the size below applies
            user32.SetWindowPos(handle, 0, area.left, area.top, area.right - area.left, area.bottom - area.top, 0x0044)  # no z-order change, show
    except (AttributeError, OSError, ValueError):
        pass


def open_window(url):
    """Open the editor in a native WebView2 window; return False on fallback."""
    if os.name == 'nt':
        brand_taskbar_identity()
        try:
            import webview
            webview.settings['ALLOW_DOWNLOADS'] = True  # Export saves through a download; pywebview cancels them all without this
            window = webview.create_window('Tessera', url, width=1500, height=980,
                                           min_size=(1050, 720), background_color='#0A0E10', text_select=True)
            webview.start(fit_to_work_area, (window,), private_mode=True, storage_path=str(ROOT / 'host/.webview-data'),
                          icon=str(ROOT / 'host/tessera.ico'))
            return True
        except Exception:
            logging.getLogger(__name__).warning('WebView2 window failed; using the browser', exc_info=True)
    webbrowser.open(url)
    return False


class Conflict(ValueError):
    pass


def installed_programs():
    """Return local Start-menu and taskbar shortcuts without launching anything."""
    if os.name != 'nt':
        return []
    roots = [
        Path(os.environ.get('APPDATA', '')) / 'Microsoft/Windows/Start Menu/Programs',
        Path(os.environ.get('PROGRAMDATA', '')) / 'Microsoft/Windows/Start Menu/Programs',
        Path(os.environ.get('APPDATA', '')) / 'Microsoft/Internet Explorer/Quick Launch/User Pinned/TaskBar',
        Path(os.environ.get('USERPROFILE', '')) / 'Desktop',
        Path(os.environ.get('PUBLIC', '')) / 'Desktop',
    ]
    ignored = ('uninstall', 'readme', 'documentation', 'manual', 'release notes', 'support')
    programs = {}
    for root in roots:
        if not root.is_dir():
            continue
        try:
            paths = root.rglob('*.lnk')
            for path in paths:
                name = path.stem.strip()
                key = name.casefold()
                if not name or any(word in key for word in ignored) or key in programs:
                    continue
                programs[key] = {'name': name, 'target': str(path)}
        except OSError:
            continue
    # Store apps are often absent from the shortcut folders. Get-StartApps is
    # the same inventory Windows Search uses and gives us stable AppsFolder IDs.
    script = ('[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); '
              'Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress')
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, text=True, encoding='utf-8', timeout=20,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        values = json.loads(result.stdout or '[]')
        if isinstance(values, dict):
            values = [values]
        for item in values:
            name, app_id = item.get('Name', '').strip(), item.get('AppID', '').strip()
            key = name.casefold()
            if name and app_id and key not in programs:
                programs[key] = {'name': name, 'target': 'shell:AppsFolder\\' + app_id}
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        pass
    return sorted(programs.values(), key=lambda item: item['name'].casefold())


def shortcut_target(path):
    if os.name != 'nt' or Path(path).suffix.lower() != '.lnk':
        return str(path)
    script = ('$shortcut=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TESSERA_LINK); '
              '[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $shortcut.TargetPath')
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                env=dict(os.environ, TESSERA_LINK=str(path)),
                                capture_output=True, text=True, encoding='utf-8', timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        value = result.stdout.strip()
        return value or str(path)
    except (OSError, subprocess.SubprocessError):
        return str(path)


class Editor:
    def __init__(self, profiles=None, controller=None, dashboard=None):
        self.path = Path(profiles or ROOT / 'host/profiles.json')
        if not self.path.exists():  # first run: the window may open before the host has created the file
            Daemon.load_profiles(self.path)
        self.controller = controller or Controller()
        self.dashboard = dashboard
        self.lock = threading.RLock()
        self.assets = Assets(self.path)
        self.firmware_job = {'state': 'idle'}
        self.last_release = None  # what the last update check found; downloads never trust client-sent URLs
        self.firmware_lock = threading.Lock()
        self.served = {}  # revision -> the configuration read then, so a save can follow a tray brightness change

    def _raw(self):
        # The file as it is on disk; empty when it is missing or locked, so a restore can still replace it.
        try:
            return self.path.read_bytes()
        except OSError:
            return b''

    def read(self):
        raw = self.path.read_bytes()
        config = validate_config(config_store.migrate(json.loads(raw)))
        revision = hashlib.sha256(raw).hexdigest()
        self.served[revision] = copy.deepcopy(config)
        while len(self.served) > 16:
            del self.served[next(iter(self.served))]
        return {'config': self.assets.heal(config), 'revision': revision}

    def rebase(self, data, raw):
        """`data` on top of a file changed only in display.brightness since the editor read it (the tray's
        Brightness menu writes the file): the editor keeps its edits, the tray's level stays. Anything else conflicts."""
        base = self.served.get(data.get('revision'))
        try:
            disk = config_store.migrate(json.loads(raw))
        except (ValueError, TypeError, KeyError, AttributeError):
            disk = None
        def without_brightness(config):
            config = copy.deepcopy(config)
            display = config.get('display') if isinstance(config, dict) else None
            level = display.pop('brightness', None) if isinstance(display, dict) else None
            if display == {}:
                del config['display']
            return config, level
        if base is None or disk is None or without_brightness(base)[0] != without_brightness(disk)[0]:
            raise Conflict('The configuration was changed in another window. Reload before saving.')
        config, level = copy.deepcopy(data['config']), without_brightness(disk)[1]
        if isinstance(config, dict) and without_brightness(config)[1] == without_brightness(base)[1]:
            display = config.get('display') if isinstance(config.get('display'), dict) else {}
            if level is None:
                display.pop('brightness', None)
            else:
                config['display'] = dict(display, brightness=level)
        return dict(data, config=config, revision=hashlib.sha256(raw).hexdigest())

    def read_for_editor(self):
        """read(), or the bundled defaults with an `error` when profiles.json is broken or from a newer Tessera.

        The editor needs some configuration to open at all, and opening is how the user reaches Restore backup.
        The revision is the broken file's, and save() refuses to overwrite it except by a restore.
        """
        try:
            return self.read()
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raw = self._raw()
            defaults = validate_config(config_store.migrate(json.loads((ROOT / 'host/profiles.default.json').read_bytes())))
            return {'config': defaults, 'revision': hashlib.sha256(raw).hexdigest(),
                    'error': f'profiles.json could not be read ({str(exc)[:200]}). Restore a backup or fix the file.'}

    def save(self, data, force_backup=False):
        with self.lock:
            raw = self._raw()
            if data.get('revision') != hashlib.sha256(raw).hexdigest():
                data = self.rebase(data, raw)
            try:
                previous = self.read()
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                # A broken (or newer) file may only be replaced by a restore, which keeps its bytes below.
                if not force_backup:
                    raise ValueError('profiles.json could not be read, so it is not overwritten. Restore a backup or fix the file.') from exc
                previous = None
            config = config_store.migrate(data['config'])
            validate_config(config)
            # Bound editor-only fields before they reach the shared action engine.
            for name, profile in config['profiles'].items():
                if not name.strip() or len(name) > 100:
                    raise ValueError('Use a profile name of 1-100 characters')
                if any(not isinstance(item, str) for item in profile.get('match', [])):
                    raise ValueError('Program rules must be text')
                for page, buttons in profile['pages'].items():
                    if not page.strip() or len(page) > 100:
                        raise ValueError('Use a page name of 1-100 characters')
                    for button in buttons:
                        icon = button.get('icon', 'ok')
                        if not isinstance(icon, str):
                            raise ValueError('The icon must be a name')
                        if icon.startswith('lc:') and icon not in icon_ids():
                            raise ValueError('The icon is not in the installed icon pack')
                        for action in button.get('actions', []):
                            if action['type'] == 'delay' and type(action.get('ms', 100)) is not int:
                                raise ValueError('The delay must be a whole number of milliseconds')
            config_store.backup(self.path, force=force_backup)
            backup = self.path.with_name(self.path.stem + '-previous.local.json')
            if previous is not None:
                save_profiles(previous['config'], backup)
            elif raw:
                backup.write_bytes(raw)  # the unreadable file, kept byte for byte
            save_profiles(config, self.path)
            return self.read()

    def status(self):
        result = self.dashboard() if self.dashboard else self.controller.status()
        return dict(result, autostart=autostart_enabled(), host_version=self.version())

    def programs(self):
        return {'programs': installed_programs()}

    def program_details(self, target, allowed_only=True):
        if not isinstance(target, str) or not target.strip() or len(target) > 2048:
            raise ValueError('Choose a valid program')
        path = Path(target)
        programs = installed_programs()
        allowed = {item['target'] for item in programs}
        if allowed_only and target not in allowed:
            raise ValueError('The program is not in the local program list')
        store_app = target.startswith('shell:AppsFolder\\')
        if not store_app and (not path.is_file() or path.suffix.lower() not in ('.exe', '.lnk', '.cmd', '.bat')):
            raise ValueError('Choose a local program file or shortcut')
        resolved = target if store_app else shortcut_target(path)
        process = Path(resolved).name if Path(resolved).suffix.lower() == '.exe' else ''
        if store_app:
            lowered = target.casefold()
            process = ('ChatGPT.exe' if 'openai.codex_' in lowered else
                       'claude.exe' if 'claude_' in lowered else
                       'XboxPcApp.exe' if 'microsoft.gamingapp_' in lowered else '')
        matched = next((item for item in programs if item['target'] == target), None)
        try:
            icon = self.assets.import_program_icon(target)['id']
        except (ValueError, OSError):
            icon = 'folder'
        return {'name': matched['name'] if matched else path.stem, 'target': target, 'process': process,
                'icon': icon, 'reuse': bool(process)}

    def icon_preferences(self, data=None):
        path = self.path.with_name('icon-library.local.json')
        if data is None:
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            return {key: [value for value in (data.get(key, []) if isinstance(data.get(key, []), list) else [])
                          if isinstance(value, str) and value in icon_ids()][:limit]
                    for key, limit in (('favorites', 512), ('recent', 24))}
        result = {}
        for key, limit in (('favorites', 512), ('recent', 24)):
            values = data.get(key, [])
            if not isinstance(values, list) or len(values) > limit or any(not isinstance(v, str) or v not in icon_ids() for v in values):
                raise ValueError('Invalid icon list')
            result[key] = list(dict.fromkeys(values))
        with self.lock:
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(result), encoding='utf-8')
            temporary.replace(path)
        return result

    # --- firmware installation -----------------------------------------------------------
    def firmware_folders(self):
        return [ROOT / 'dist', ROOT / 'firmware', ROOT / 'host/firmware']

    def firmware_list(self):
        status = self.status().get('device', {})
        version_file = ROOT / 'VERSION'
        return {'packages': firmware_update.find_packages(self.firmware_folders(), SUPPORTED_PROTOCOLS),
                'device': {'firmware': status.get('firmware'), 'protocol': status.get('protocol'),
                           'connected': bool(status.get('connected'))},
                'host': version_file.read_text(encoding='utf-8').strip() if version_file.is_file() else None,
                'job': dict(self.firmware_job)}

    @staticmethod
    def identify_panel(port):
        # get_info of the panel on `port`; None when it stays silent; PackageError for another device.
        try:
            panel = PanelSerial(port, lambda *_: None)
        except DeviceRejected as exc:
            if exc.kind == 'silent':
                return None
            if exc.kind == 'protocol':
                return {'boardId': firmware_update.BOARD_ID, 'firmwareVersion': None}
            raise firmware_update.PackageError(str(exc)) from exc
        except OSError as exc:
            raise firmware_update.InstallError(f'{port} could not be opened: {exc}') from exc
        info = dict(panel.info)
        panel.close()
        return info

    def install_firmware(self, data):
        path, mode, force = data.get('package'), data.get('mode', 'app'), data.get('force', False)
        if not isinstance(path, str) or mode not in ('app', 'full') or type(force) is not bool:
            raise ValueError('Choose a firmware package and an install mode')
        package = firmware_update.load_package(Path(path), SUPPORTED_PROTOCOLS)
        if not self.firmware_lock.acquire(blocking=False):
            raise ValueError('A firmware installation is already running')
        self.firmware_job = {'state': 'running', 'stage': 'checking', 'percent': 0, 'version': package.version}
        threading.Thread(target=self.run_firmware_install, args=(package, mode, force),
                         name='firmware-install', daemon=True).start()
        return {'message': f'Installing firmware {package.version} ...'}

    def firmware_port(self):
        # The first candidate is only TESSERA_PORT/COM4 when no panel is remembered, so it is not trusted: the port
        # whose device answers as a panel wins. Without an answer (a blank panel) only a lone Espressif port is used,
        # so "Install anyway" never writes to another device or to a second ESP32.
        import host_runtime
        try:
            installed = host_runtime._installed_ports()
            espressif = sorted(host_runtime._espressif_ports())
        except (ImportError, OSError):
            installed, espressif = {}, []
        ports = [port for port in host_runtime.candidate_ports(os.environ.get('TESSERA_PORT', 'COM4'),
                                                               ROOT / 'host/deck-device.local.json', installed, espressif)
                 if port in installed]
        rejected = set()
        for port in ports:
            try:
                if self.identify_panel(port) is not None:
                    return port
            except firmware_update.PackageError:
                rejected.add(port)  # another device answered: never flash it, not even as the lone Espressif port
            except firmware_update.InstallError:
                continue  # a port that is busy: try the next one
        if len(espressif) == 1 and espressif[0] not in rejected:
            return espressif[0]
        if not ports:
            raise firmware_update.InstallError('No USB port was found. Connect the panel with the USB cable.')
        raise firmware_update.InstallError(f'No Tessera panel answered on {", ".join(ports)}. Unplug the other '
                                           'USB serial devices, or connect only the panel, and try again.')

    def run_firmware_install(self, package, mode, force):
        was_running = bool(self.controller.processes())
        outcome = {'state': 'failed', 'error': 'The install was interrupted'}
        try:
            # the tray greys out Start host and holds its "host is not running" notice while this file exists
            try:
                FIRMWARE_FLAG_PATH.write_text(json.dumps({'pid': os.getpid()}), encoding='utf-8')
            except OSError:
                pass  # the editor still refuses Start; a missing flag must not block the install
            if was_running:
                self.controller.stop()  # the host is the only owner of the USB port

            def progress(stage, percent):
                self.firmware_job = dict(self.firmware_job, stage=stage, percent=round(percent))

            result = firmware_update.install(package, self.firmware_port(), self.identify_panel, mode, force, progress)
            outcome = {'state': 'done', 'stage': 'done', 'percent': 100, 'result': result}
        except Exception as exc:  # whatever went wrong, the job must not stay "running" forever
            outcome = {'state': 'failed', 'error': str(exc) or type(exc).__name__}
        finally:
            # the outcome is published after the restart, so the dialog never says the host is back before it is
            try:
                FIRMWARE_FLAG_PATH.unlink(missing_ok=True)  # before the restart, which the flag would refuse
                if was_running:
                    self.controller.start()
                    outcome['restarted'] = True
            except Exception as exc:
                outcome['restart_error'] = str(exc) or type(exc).__name__
            self.firmware_job = dict(self.firmware_job, **outcome)
            self.firmware_lock.release()

    def dry_run(self, data):
        # What pressing a button would do, explained without doing any of it.
        groups = {key: data.get(key) for key in ('actions', 'hold_actions', 'double_actions') if data.get(key) is not None}
        if not groups or any(not isinstance(value, list) or len(value) > 50
                             or any(not isinstance(item, dict) for item in value) for value in groups.values()):
            raise ValueError('Send the button actions as lists of at most 50 steps')
        variables = self.status().get('variables') or {}
        return {key: preview(value, variables) for key, value in groups.items()}

    def version(self):
        version_file = ROOT / 'VERSION'
        return version_file.read_text(encoding='utf-8').strip() if version_file.is_file() else '0.0.0'

    def check_updates(self):
        try:
            self.last_release = updates.check(self.version())
        except OSError as exc:
            raise ValueError('GitHub could not be reached. Check your internet connection.') from exc
        return self.last_release

    def download_firmware(self):
        if not self.last_release:
            raise ValueError('Check for updates first')
        try:
            path = updates.download_firmware(self.last_release, ROOT / 'firmware')
        except OSError as exc:
            raise ValueError('The download failed. Check your internet connection and try again.') from exc
        return {'path': str(path), 'message': f'Downloaded and verified {path.name}. Choose it in the firmware list.'}

    def export_diagnostics(self):
        target = diagnostics.build(ROOT / 'diagnostics', self.read()['config'], self.status(), self.version(),
                                   ROOT / 'host/deck.local.log')
        if os.name == 'nt':
            os.startfile(target.parent)
        return {'path': str(target), 'message': f'Saved {target.name} in the diagnostics folder. It contains no button contents.'}

    def claude_hooks(self, data):
        """Read (no `events`/`permission` in data) or change the Claude Code hooks that feed the agents screen."""
        import claude_setup
        if 'events' not in data and 'permission' not in data:
            return claude_setup.state()
        python = ROOT / 'host/.venv/Scripts/python.exe'
        return claude_setup.update(data.get('events'), data.get('permission'), python if python.is_file() else Path(sys.executable),
                                   ROOT / 'host/deckctl.py')

    def plugin_list(self):
        # Installed plugins with their configuration and, when the host runs, their live state.
        manifests, problems = plugins.discover(ROOT / 'plugins')
        live = {item['id']: item for item in self.status().get('plugins', [])}
        configured = self.read()['config'].get('plugins', {})
        rows = []
        for manifest in manifests:
            entry = configured.get(manifest.id, {})
            enabled = bool(entry.get('enabled'))
            state = live.get(manifest.id, {})
            rows.append({'id': manifest.id, 'name': manifest.name, 'version': manifest.version,
                         'permissions': sorted(manifest.permissions), 'settings': manifest.settings, 'enabled': enabled,
                         'values': entry.get('settings', {}),
                         'state': state.get('state', 'starting' if enabled else 'disabled') if enabled else 'disabled',
                         'error': state.get('error', '')})
        return {'plugins': rows, 'problems': problems}

    def restore_backup(self, name):
        # Put a backup back in place; the configuration it replaces is backed up first.
        config = config_store.read_backup(self.path, name)
        validate_config(config)
        # The raw hash, not read(): the file being replaced may be the broken one this restore is for.
        return self.save({'config': config, 'revision': hashlib.sha256(self._raw()).hexdigest()}, force_backup=True)

    def command(self, command, data):
        if command == 'host-log':
            return {'log': diagnostics.log_tail(ROOT / 'host/deck.local.log', int(data.get('lines', 200)) if isinstance(data.get('lines', 200), int) else 200)}
        if command == 'update-check':
            return self.check_updates()
        if command == 'update-download-firmware':
            return self.download_firmware()
        if command == 'diagnostics':
            return self.export_diagnostics()
        if command == 'claude-hooks':
            return self.claude_hooks(data)
        if command == 'plugins':
            return self.plugin_list()
        if command == 'backups':
            return {'backups': config_store.list_backups(self.path)}
        if command == 'restore-backup':
            return self.restore_backup(data.get('name'))
        if command == 'dryrun':
            return self.dry_run(data)
        if command in ('iconify-search', 'iconify-svg'):
            try:
                if command == 'iconify-search':
                    return {'icons': iconify.search(str(data.get('query', '')))}
                return {'svg': iconify.svg(str(data.get('id', '')), str(data.get('color', '#FFFFFF')))}
            except OSError as exc:
                raise ValueError('The icon service could not be reached. Check your internet connection.') from exc
        if command == 'weather-search':
            try:
                return {'places': ambient.search_places(str(data.get('query', '')))}
            except OSError as exc:
                raise ValueError('The city search could not be reached. Check your internet connection.') from exc
        if command == 'firmware-list':
            return self.firmware_list()
        if command == 'firmware-install':
            return self.install_firmware(data)
        if command == 'firmware-progress':
            return {'job': dict(self.firmware_job)}
        if command == 'review':
            config = validate_config(data.get('config') or {})
            return {'findings': review(config)}
        if command == 'sanitize':
            return {'config': strip_executable(validate_config(data.get('config') or {}))}
        if command == 'activate':
            config = self.read()['config']
            profile, page = data.get('profile'), data.get('page')
            if profile not in config['profiles'] or page not in config['profiles'][profile]['pages']:
                raise ValueError('Choose a valid profile and page')
            path = ROOT / 'host/deck-command.local.json'
            temporary = path.with_suffix('.tmp')
            with self.lock:
                temporary.write_text(json.dumps({'profile': profile, 'page': page}), encoding='utf-8')
                temporary.replace(path)
            return {'message': 'The page was sent to the host. The panel updates when USB is connected.'}
        if command in ('start', 'stop'):
            if self.firmware_job.get('state') == 'running':
                # a host started between the panel check and esptool takes the COM port and breaks the flash
                raise ValueError('The panel firmware is being installed. The host starts again when it is done.')
            output = []
            with self.lock:
                getattr(self.controller, command)(emit=output.append)
            return {'message': 'The host has started.' if command == 'start' else 'The host has stopped.'}
        if command == 'terminal':
            subprocess.Popen([sys.executable, str(ROOT / 'host/tessera_terminal.py')], cwd=ROOT,
                             creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
            return {'message': 'The deck terminal has been opened.'}
        if command == 'autostart':
            enabled = data.get('enabled')
            if type(enabled) is not bool:
                raise ValueError('Choose whether automatic startup is on or off')
            set_autostart(enabled)
            return {'message': ('The USB host starts automatically at sign-in.' if enabled
                                else 'Automatic startup is turned off.')}
        if command == 'pick':
            kind = data.get('kind', 'file')
            if kind not in ('file', 'program'):
                raise ValueError('Unknown file picker')
            result = subprocess.run([sys.executable, str(ROOT / 'host/editor_file_picker.py'), kind],
                                    capture_output=True, text=True, encoding='utf-8', timeout=180,
                                    env=dict(os.environ, PYTHONUTF8='1'),
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if result.returncode:
                raise ValueError('The file picker could not be opened. You can paste the path into the field.')
            path = result.stdout.strip()
            if kind == 'program' and path:
                return self.program_details(path, allowed_only=False)
            return {'path': path}
        if command == 'program':
            return self.program_details(data.get('target', ''))
        raise ValueError('Unknown command')


def make_server(editor, port=0, token=None):
    token = token or secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log user actions, paths or session tokens.

        def headers_common(self):
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")

        def json(self, value, code=200, cookie=False):
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(code)
            self.headers_common()
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            if cookie:
                self.send_header('Set-Cookie', f'deck_session_{self.server.server_port}={token}; HttpOnly; SameSite=Strict; Path=/')
            self.end_headers()
            self.wfile.write(raw)

        def allowed(self):
            host = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != host:
                self.json({'error': 'Invalid local address'}, 403)
                return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + host:
                self.json({'error': 'Invalid origin'}, 403)
                return False
            return True

        def authenticated(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie', ''))
                name = f'deck_session_{self.server.server_port}'
                supplied = cookie[name].value if name in cookie else ''
            except Exception:
                supplied = ''
            return secrets.compare_digest(supplied, token)

        def do_GET(self):
            if not self.allowed():
                return
            if self.path.startswith('/api/image/'):
                if not self.authenticated():
                    return self.json({'error': 'Invalid session'}, 401)
                try:
                    raw = editor.assets.preview(self.path.removeprefix('/api/image/'))
                except (ValueError, OSError):
                    return self.json({'error': 'The image does not exist'}, 404)
                self.send_response(200)
                self.headers_common()
                self.send_header('Content-Type', 'image/png')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                return self.wfile.write(raw)
            if self.path in ('/api/config', '/api/status', '/api/icons', '/api/action-packs', '/api/export', '/api/processes', '/api/programs'):
                if not self.authenticated():
                    return self.json({'error': 'Open the editor from Tessera.cmd'}, 401)
                try:
                    if self.path == '/api/export':
                        config = editor.read()['config']
                        shared, secrets_used = redact_secrets(config)
                        return self.json(dict(shared, assets=editor.assets.export(config), redacted=secrets_used))
                    if self.path == '/api/processes':
                        import psutil
                        names = set()
                        for process in psutil.process_iter(['name']):
                            name = process.info.get('name')
                            if name:
                                names.add(name.lower())
                        return self.json({'names': sorted(names)})
                    if self.path == '/api/programs':
                        return self.json(editor.programs())
                    if self.path == '/api/action-packs':
                        return self.json(action_pack_catalog())
                    return self.json(editor.read_for_editor() if self.path == '/api/config' else dict(icon_catalog(), preferences=editor.icon_preferences()) if self.path == '/api/icons' else editor.status())
                except ValueError as exc:
                    return self.json({'error': str(exc) or 'Could not read the local configuration'}, 400)
                except (OSError, TypeError):
                    return self.json({'error': 'Could not read the local configuration'}, 400)
            files = {'/': 'index.html', '/core.js': 'core.js', '/app.js': 'app.js', '/dialogs.js': 'dialogs.js',
                     '/style.css': 'style.css',
                     '/streamdeck.css': 'streamdeck.css', '/cockpit.css': 'cockpit.css', '/logo-mark.svg': 'logo-mark.svg'}
            if self.path not in files:
                return self.json({'error': 'Not found'}, 404)
            file = WEB / files[self.path]
            raw = file.read_bytes()
            self.send_response(200)
            self.headers_common()
            self.send_header('Content-Type', {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
                                              '.svg': 'image/svg+xml'}[file.suffix] + '; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            if not self.allowed():
                return
            session = self.path == '/api/session'
            if session:
                if not secrets.compare_digest(self.headers.get('X-Deck-Token', ''), token):
                    return self.json({'error': 'Invalid session'}, 403)
            elif not self.authenticated() or self.headers.get('X-Deck-Request') != '1':
                return self.json({'error': 'Invalid session'}, 403)
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 <= length <= (12 * 1024 * 1024 if self.path == '/api/image' else 1024 * 1024):
                    return self.json({'error': 'The configuration is too large'}, 413)
                if self.headers.get_content_type() != 'application/json':
                    return self.json({'error': 'Expected JSON'}, 415)
                data = json.loads(self.rfile.read(length), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid number')))
                if not isinstance(data, dict):
                    raise ValueError('Invalid configuration')
                if session:
                    return self.json({'ok': True}, cookie=True)
                if self.path == '/api/config':
                    return self.json(editor.save(data))
                if self.path == '/api/icon-preferences':
                    return self.json(editor.icon_preferences(data))
                if self.path == '/api/image':
                    return self.json(editor.assets.import_image(data['data']))
                if self.path.startswith('/api/command/'):
                    return self.json(editor.command(self.path.removeprefix('/api/command/'), data))
                return self.json({'error': 'Not found'}, 404)
            except Conflict as exc:
                self.json({'error': str(exc)}, 409)
            except (ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
                self.json({'error': str(exc) if isinstance(exc, ValueError) else 'Invalid configuration'}, 400)
            except RuntimeError as exc:  # for example the host could not start; RecursionError is caught above
                self.json({'error': str(exc)}, 400)
            except (OSError, subprocess.SubprocessError) as exc:
                self.json({'error': f'The operation could not be completed: {exc}'}, 400)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.token = token
    server.editor = editor
    return server


def show_running_editor(record, build, open_if_hidden=False):
    """Bring the running editor to the front. False when there is none yet; an editor of another build is stopped.

    The editor's server answers a moment before its window is on screen. Opening a window of our own then (the
    old behaviour) is how a double click made two; the caller waits and asks again instead.
    """
    import psutil
    try:
        previous = json.loads(record.read_text())
        process = psutil.Process(previous['pid'])
        command = process.cmdline()
        address = urllib.parse.urlsplit(previous['url'])
        own_process = len(command) > 1 and Path(command[1]).resolve() == Path(__file__).resolve()
        local_address = address.scheme == 'http' and address.hostname == '127.0.0.1' and address.port and address.path == '/'
        if not (own_process and local_address and abs(process.create_time() - previous['created']) < .01):
            return False
        request = urllib.request.Request(previous['url'] + 'api/session', data=b'{}',
                                         headers={'Content-Type': 'application/json', 'X-Deck-Token': previous['token']})
        with urllib.request.urlopen(request, timeout=2) as response:
            if response.status != 200:
                return False
        if previous.get('build') == build:
            if previous.get('browser'):  # the editor runs in a browser tab, which has no window of its own to raise
                webbrowser.open(previous['url'] + '#' + previous['token'])
                return True
            if activate_window(previous['pid']):
                return True
            if open_if_hidden:
                open_window(previous['url'] + '#' + previous['token'])
                return True
            return False
        # A launcher reopening an updated editor must not reuse a stale API server. The independent USB host stays up.
        process.terminate()
        process.wait(timeout=3)
    except (OSError, ValueError, KeyError, psutil.Error):
        pass
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--terminal', action='store_true')
    parser.add_argument('--editor', action='store_true', help='Open the graphical drag-and-drop editor')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--profiles', type=Path)
    args = parser.parse_args()
    if args.terminal or args.check:
        return subprocess.call([sys.executable, str(ROOT / 'host/tessera_terminal.py')]
                               + (['--check'] if args.check else []), cwd=ROOT)
    controller = Controller()
    controller.install_adapters()
    record = ROOT / 'host/editor.local.json'
    build = editor_build_id()
    # One editor window: a second start (a double click on the tray icon, a click while the first is still
    # starting) waits for the first one and brings its window to the front instead of opening another.
    lock = InstanceLock(ROOT / 'host/editor.local.lock')
    if not args.profiles and not args.no_browser:
        deadline = time.monotonic() + 20
        while not lock.acquire():
            if show_running_editor(record, build) or time.monotonic() > deadline:
                return
            time.sleep(.3)
        if show_running_editor(record, build, open_if_hidden=True):  # an editor from before the lock existed
            lock.release()
            return
    server = make_server(Editor(args.profiles, controller), args.port)
    url = f'http://127.0.0.1:{server.server_port}/'
    if not args.profiles:
        import psutil
        from control_api import make_private
        details = {'pid': os.getpid(), 'created': psutil.Process().create_time(), 'url': url, 'token': server.token, 'build': build}

        def write_record():
            temporary = record.with_suffix('.tmp')
            temporary.write_text(json.dumps(details), encoding='utf-8')
            make_private(temporary)  # the token opens the editor's API: other accounts must not read it
            os.replace(temporary, record)
        write_record()
    print('The Tessera editor is open. Keep this window open.', flush=True)
    server_thread = None
    try:
        if not args.no_browser:
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            if open_window(url + '#' + server.token):
                server.shutdown()
                server_thread.join(timeout=3)
                return
            if not args.profiles:  # no window of our own: the next start opens another browser tab at once
                details['browser'] = True
                write_record()
            while server_thread.is_alive():
                server_thread.join(timeout=.5)
        else:
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        lock.release()
        if not args.profiles:
            try:
                if json.loads(record.read_text()).get('pid') == os.getpid():
                    record.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass


if __name__ == '__main__':
    raise SystemExit(main())
