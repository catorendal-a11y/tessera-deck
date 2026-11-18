"""Starting Tessera when the user signs in on Linux: an XDG autostart entry (the Windows counterpart is
platform_windows/autostart.py with the same functions)."""
from pathlib import Path

from platform_linux import desktop_entries
from venv_paths import venv_python


def startup_script_path(appdata=None):
    """The autostart entry. `appdata` replaces the XDG config folder (the tests use it)."""
    return desktop_entries.autostart_path(appdata)


def is_enabled(script, root):
    return Path(script).is_file()


def enable(path, root):
    """Write the autostart entry. Needs the virtual environment that Tessera.sh makes."""
    python = venv_python(root)
    if not python.is_file():
        raise OSError('Run Tessera.sh once before enabling automatic startup')
    return desktop_entries.write(path, desktop_entries.entry([str(python), str(root / 'host/tessera_tray.py')], root,
                                                             root / 'docs/images/logo-mark.svg', hidden_start=True))
