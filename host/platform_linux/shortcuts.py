"""The application menu entries of Tessera on Linux (the Windows counterpart is the Desktop shortcut in
platform_windows/shortcuts.py, with the same functions). There are two, made from the files in host/linux/: one for the tray and
the host, one for the editor."""
from pathlib import Path

from platform_linux import desktop_entries

ENTRIES = ('tessera-tray.desktop', 'tessera-editor.desktop')


def desktop_shortcut_path() -> Path:
    return desktop_entries.launcher_path().with_name(ENTRIES[0])


def shortcut_files(link: Path) -> list[Path]:
    """Every file `create_shortcut` writes for `link` (the tray entry), and the single entry earlier versions wrote."""
    others = [link.with_name(name) for name in (*ENTRIES, desktop_entries.NAME) if name != link.name]
    return [link, *others]


def create_shortcut(target: Path, link: Path) -> Path:
    """The tray and the editor entries next to `link`; Tessera.cmd means the Tessera.sh next to it. Returns the tray entry."""
    target = target if target.name != 'Tessera.cmd' else target.with_name('Tessera.sh')
    for name in ENTRIES:
        template = (target.parent / 'host/linux' / name).read_text(encoding='utf-8')
        desktop_entries.write(link.with_name(name), desktop_entries.from_template(
            template, target, target.parent, target.parent / 'docs/images/logo-mark.svg'))
    link.with_name(desktop_entries.NAME).unlink(missing_ok=True)  # the one entry of earlier versions
    return link.with_name(ENTRIES[0])
