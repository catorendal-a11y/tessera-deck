"""The Desktop shortcut (.lnk) of Tessera on Windows."""
import os
from pathlib import Path
import subprocess


def desktop_shortcut_path() -> Path:
    folder = ''
    # ask Windows: the Desktop may have been moved, for example into OneDrive
    import ctypes
    buffer = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) == 0:
        folder = buffer.value
    return Path(folder or os.path.expandvars(r'%USERPROFILE%\Desktop')) / 'Tessera.lnk'


def shortcut_files(link: Path) -> list[Path]:
    """Every file `create_shortcut` writes for `link`."""
    return [link]


def create_shortcut(target: Path, link: Path) -> Path:
    """A Desktop shortcut with the Tessera icon that starts the program minimised."""
    # `powershell -Command` does not expose trailing arguments as $args, so the values travel as environment variables.
    script = ('$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TESSERA_LINK);$s.TargetPath=$env:TESSERA_TARGET;'
              '$s.WorkingDirectory=$env:TESSERA_FOLDER;$s.IconLocation=$env:TESSERA_ICON;$s.WindowStyle=7;$s.Save()')
    environment = dict(os.environ, TESSERA_LINK=str(link), TESSERA_TARGET=str(target), TESSERA_FOLDER=str(target.parent),
                       TESSERA_ICON=str(target.parent / 'host/tessera.ico'))
    link.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], env=environment,
                            capture_output=True, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise OSError(result.stderr.strip() or 'The shortcut could not be created')
    return link
