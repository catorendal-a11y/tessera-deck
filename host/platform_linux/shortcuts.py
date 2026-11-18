"""The application menu entry of Tessera on Linux (the Windows counterpart is the Desktop shortcut in
platform_windows/shortcuts.py, with the same functions)."""
from pathlib import Path

from platform_linux import desktop_entries


def desktop_shortcut_path() -> Path:
    return desktop_entries.launcher_path()


def create_shortcut(target: Path, link: Path) -> Path:
    """An application menu entry with the Tessera icon; Tessera.cmd means the Tessera.sh next to it."""
    target = target if target.name != 'Tessera.cmd' else target.with_name('Tessera.sh')
    return desktop_entries.write(link, desktop_entries.entry([str(target)], target.parent,
                                                             target.parent / 'docs/images/logo-mark.svg'))
