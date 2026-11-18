"""The Windows shell from Python: PowerShell, shortcuts (.lnk) and the Start menu."""
import json
import os
from pathlib import Path
import subprocess


def _powershell(script, timeout, env=None):
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], env=env,
                          capture_output=True, text=True, encoding='utf-8', timeout=timeout,
                          creationflags=subprocess.CREATE_NO_WINDOW)


def shortcut_target(path):
    if os.name != 'nt' or Path(path).suffix.lower() != '.lnk':
        return str(path)
    script = ('$shortcut=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TESSERA_LINK); '
              '[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $shortcut.TargetPath')
    try:
        result = _powershell(script, 10, env=dict(os.environ, TESSERA_LINK=str(path)))
        value = result.stdout.strip()
        return value or str(path)
    except (OSError, subprocess.SubprocessError):
        return str(path)


def scan_programs():
    return scan_start_menu()


def scan_start_menu():
    """Local Start-menu and taskbar shortcuts and Store apps, without launching anything."""
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
        result = _powershell(script, 20)
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
