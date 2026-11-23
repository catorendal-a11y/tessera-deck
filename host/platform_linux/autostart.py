"""Starting Tessera when the user signs in on Linux: an XDG autostart entry (the Windows counterpart is
platform_windows/autostart.py with the same functions)."""
import os
from pathlib import Path

from platform_linux import desktop_entries
from venv_paths import venv_python


def startup_script_path(appdata=None):
    """The autostart entry. `appdata` replaces the XDG config folder (the tests use it)."""
    return desktop_entries.autostart_path(appdata)


# The Arch package runs a per-user copy through /usr/bin/tessera, which refreshes the copy after a package update and sets
# TESSERA_PACKAGED. An entry that starts the copy's python directly would skip both.
PACKAGED_COMMAND = ['tessera', '--tray']


def packaged(root):
    """True in the Arch package's per-user copy. A tray started by an entry from 1.2.11 or older runs without
    TESSERA_PACKAGED, so the .pkgrel file that the launcher copies in with the package counts too."""
    return bool(os.environ.get('TESSERA_PACKAGED')) or (Path(root) / '.pkgrel').is_file()


def is_enabled(script, root):
    """True when the entry starts the tray of this folder. An entry left by a copy in another folder does not count.
    In the Arch copy, an older entry that starts the copy's python is rewritten to start the wrapper."""
    tray = str(Path(root) / 'host/tessera_tray.py')
    try:
        text = Path(script).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return False
    if not packaged(root):
        return tray in text
    if tray in text:
        try:
            enable(Path(script), Path(root))
        except OSError:
            pass  # the old entry still starts this copy
        return True
    return desktop_entries.quote(PACKAGED_COMMAND) in text


def enable(path, root):
    """Write the autostart entry. Needs the virtual environment that Tessera.sh makes."""
    if packaged(root):
        return desktop_entries.write(path, desktop_entries.entry(PACKAGED_COMMAND, root, root / 'docs/images/logo-mark.svg',
                                                                 hidden_start=True))
    python = venv_python(root)
    if not python.is_file():
        raise OSError('Run Tessera.sh once before enabling automatic startup')
    return desktop_entries.write(path, desktop_entries.entry([str(python), str(root / 'host/tessera_tray.py')], root,
                                                             root / 'docs/images/logo-mark.svg', hidden_start=True))
