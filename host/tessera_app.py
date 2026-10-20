"""Local graphical editor for the standalone Tessera."""
import argparse
import hashlib
from functools import lru_cache
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import urllib.request
import urllib.parse
import webbrowser

from deck_control import (ROOT, Controller, autostart_enabled, configure_upstream,
                          save_profiles, set_autostart)
from tesserad import SUPPORTED_PROTOCOLS, DeviceRejected, PanelSerial, validate_config
from deck_assets import Assets
import ambient
import config_store
import diagnostics
import firmware_update
import iconify
import updates
from action_preview import preview
from import_review import redact_secrets, review, strip_executable

WEB = Path(__file__).with_name('editor')


def editor_build_id():
    """Fingerprint every file cached or imported by the long-lived editor."""
    digest = hashlib.sha256()
    files = [Path(__file__), ROOT / 'host/deck_control.py', ROOT / 'host/deck_assets.py',
             ROOT / 'host/tesserad.py', ROOT / 'host/action_packs.json',
             WEB / 'index.html', WEB / 'style.css', WEB / 'app.js']
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
        user32.ShowWindow(found[0], 9)
        user32.SetForegroundWindow(found[0])
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


def open_window(url):
    """Open the editor in a native WebView2 window; return False on fallback."""
    if os.name == 'nt':
        brand_taskbar_identity()
        try:
            import webview
            webview.create_window('Tessera', url, width=1500, height=980,
                                           min_size=(1050, 720), maximized=True,
                                           background_color='#101719', text_select=True)
            webview.start(private_mode=True, storage_path=str(ROOT / 'host/.webview-data'),
                          icon=str(ROOT / 'host/tessera.ico'))
            return True
        except Exception:
            pass
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
    script = ('$shortcut=(New-Object -ComObject WScript.Shell).CreateShortcut($args[0]); '
              '[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $shortcut.TargetPath')
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script, str(path)],
                                capture_output=True, text=True, encoding='utf-8', timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        value = result.stdout.strip()
        return value or str(path)
    except (OSError, subprocess.SubprocessError):
        return str(path)


class Editor:
    def __init__(self, profiles=None, controller=None, dashboard=None):
        self.path = Path(profiles or ROOT / 'host/profiles.json')
        self.controller = controller or Controller()
        self.dashboard = dashboard
        self.lock = threading.RLock()
        self.assets = Assets(self.path)
        self.firmware_job = {'state': 'idle'}
        self.last_release = None  # what the last update check found; downloads never trust client-sent URLs
        self.firmware_lock = threading.Lock()

    def read(self):
        raw = self.path.read_bytes()
        config = validate_config(config_store.migrate(json.loads(raw)))
        return {'config': self.assets.heal(config), 'revision': hashlib.sha256(raw).hexdigest()}

    def save(self, data, force_backup=False):
        with self.lock:
            previous = self.read()
            if data.get('revision') != previous['revision']:
                raise Conflict('The configuration was changed in another window. Reload before saving.')
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
            save_profiles(previous['config'], backup)
            save_profiles(config, self.path)
            return self.read()

    def status(self):
        result = self.dashboard() if self.dashboard else self.controller.status()
        return dict(result, autostart=autostart_enabled())

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
        from host_runtime import candidate_ports
        ports = candidate_ports(os.environ.get('TESSERA_PORT', 'COM4'), ROOT / 'host/deck-device.local.json')
        if not ports:
            raise firmware_update.InstallError('No USB port was found. Connect the panel with the USB cable.')
        return ports[0]

    def run_firmware_install(self, package, mode, force):
        was_running = bool(self.controller.processes())
        try:
            if was_running:
                self.controller.stop()  # the host is the only owner of the USB port

            def progress(stage, percent):
                self.firmware_job = dict(self.firmware_job, stage=stage, percent=round(percent))

            result = firmware_update.install(package, self.firmware_port(), self.identify_panel, mode, force, progress)
            self.firmware_job = dict(self.firmware_job, state='done', stage='done', percent=100, result=result)
        except (firmware_update.InstallError, firmware_update.PackageError, OSError, RuntimeError, ValueError) as exc:
            self.firmware_job = dict(self.firmware_job, state='failed', error=str(exc))
        finally:
            try:
                if was_running:
                    self.controller.start()
            except (OSError, RuntimeError) as exc:
                self.firmware_job = dict(self.firmware_job, restart_error=str(exc))
            self.firmware_lock.release()

    def dry_run(self, data):
        # What pressing a button would do, explained without doing any of it.
        groups = {key: data.get(key) for key in ('actions', 'hold_actions') if data.get(key) is not None}
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

    def restore_backup(self, name):
        # Put a backup back in place; the configuration it replaces is backed up first.
        config = config_store.read_backup(self.path, name)
        validate_config(config)
        return self.save({'config': config, 'revision': self.read()['revision']}, force_backup=True)

    def command(self, command, data):
        if command == 'update-check':
            return self.check_updates()
        if command == 'update-download-firmware':
            return self.download_firmware()
        if command == 'diagnostics':
            return self.export_diagnostics()
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
                    return self.json(editor.read() if self.path == '/api/config' else dict(icon_catalog(), preferences=editor.icon_preferences()) if self.path == '/api/icons' else editor.status())
                except (ValueError, OSError, TypeError):
                    return self.json({'error': 'Could not read the local configuration'}, 400)
            files = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
            if self.path not in files:
                return self.json({'error': 'Not found'}, 404)
            file = WEB / files[self.path]
            raw = file.read_bytes()
            self.send_response(200)
            self.headers_common()
            self.send_header('Content-Type', mimetypes.guess_type(file)[0] + '; charset=utf-8')
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
                    return self.json({'error': 'Forventet JSON'}, 415)
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
            except (OSError, subprocess.SubprocessError):
                self.json({'error': 'The operation could not be completed. Check the configuration in the terminal.'}, 400)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.token = token
    server.editor = editor
    return server


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
    configure_upstream()
    controller = Controller()
    controller.install_adapters()
    record = ROOT / 'host/editor.local.json'
    build = editor_build_id()
    if not args.profiles and not args.no_browser:
        try:
            import psutil
            previous = json.loads(record.read_text())
            process = psutil.Process(previous['pid'])
            command = process.cmdline()
            address = urllib.parse.urlsplit(previous['url'])
            own_process = len(command) > 1 and Path(command[1]).resolve() == Path(__file__).resolve()
            local_address = address.scheme == 'http' and address.hostname == '127.0.0.1' and address.port and address.path == '/'
            if own_process and local_address and abs(process.create_time() - previous['created']) < .01:
                request = urllib.request.Request(previous['url'] + 'api/session', data=b'{}',
                    headers={'Content-Type': 'application/json', 'X-Deck-Token': previous['token']})
                with urllib.request.urlopen(request, timeout=1) as response:
                    if response.status == 200:
                        if previous.get('build') == build:
                            if not activate_window(previous['pid']):
                                open_window(previous['url'] + '#' + previous['token'])
                            return
                        # A launcher reopening an updated editor must not reuse
                        # a stale API server. The independent USB host stays up.
                        process.terminate()
                        process.wait(timeout=3)
        except (OSError, ValueError, KeyError, psutil.Error):
            pass
    server = make_server(Editor(args.profiles, controller), args.port)
    url = f'http://127.0.0.1:{server.server_port}/'
    if not args.profiles:
        import psutil
        record.write_text(json.dumps({'pid': os.getpid(), 'created': psutil.Process().create_time(),
                                      'url': url, 'token': server.token, 'build': build}), encoding='utf-8')
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
            while server_thread.is_alive():
                server_thread.join(timeout=.5)
        else:
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if not args.profiles:
            try:
                if json.loads(record.read_text()).get('pid') == os.getpid():
                    record.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass


if __name__ == '__main__':
    raise SystemExit(main())
