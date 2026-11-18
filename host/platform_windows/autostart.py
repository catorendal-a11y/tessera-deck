"""Starting Tessera when the user signs in to Windows: a Tessera.vbs script in the per-user Startup folder."""
import os
from pathlib import Path


def startup_script_path(appdata=None):
    """Return the per-user Windows Startup shortcut script."""
    base = Path(appdata or os.environ.get('APPDATA', ''))
    if not str(base):
        raise OSError('The Windows startup folder is not available')
    return base / 'Microsoft/Windows/Start Menu/Programs/Startup/Tessera.vbs'


def startup_line(root):
    """The line of Tessera.vbs that starts the tray app of this folder."""
    command = f'"{root / "host/.venv/Scripts/pythonw.exe"}" "{root / "host/tessera_tray.py"}"'.replace('"', '""')
    return f'TesseraShell.Run "{command}", 0, False'


def is_enabled(script, root):
    """True when the script at `script` starts this folder. A script left by a copy in another folder does not count."""
    try:
        data = Path(script).read_bytes()
        return startup_line(root) in data.decode('utf-16' if data[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8')  # 0.5-0.6.1 wrote UTF-8
    except (OSError, UnicodeError):
        return False


def enable(path, root):
    """Write the startup script. Needs the virtual environment that Tessera.cmd makes."""
    if not (root / 'host/.venv/Scripts/pythonw.exe').is_file():
        raise OSError('Run Tessera.cmd once before enabling automatic startup')
    contents = f'Set TesseraShell = CreateObject("WScript.Shell")\r\n{startup_line(root)}\r\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(contents, encoding='utf-16')  # Script Host reads a non-ASCII path only as UTF-16
    os.replace(temporary, path)
    return path
