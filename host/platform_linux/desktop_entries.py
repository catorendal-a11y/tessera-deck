"""The .desktop files Tessera writes on Linux: the autostart entry and the application launcher."""
from __future__ import annotations

import os
from pathlib import Path

NAME = 'tessera.desktop'


def config_home(environ=None) -> Path:
    environ = os.environ if environ is None else environ
    return Path(environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')


def data_home(environ=None) -> Path:
    environ = os.environ if environ is None else environ
    return Path(environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')


def autostart_path(config=None) -> Path:
    return Path(config or config_home()) / 'autostart' / NAME


def launcher_path(data=None) -> Path:
    return Path(data or data_home()) / 'applications' / NAME


def quote(command: list[str]) -> str:
    """A command as the Exec key of a Desktop Entry takes it: every word quoted as the specification says."""
    return ' '.join('"' + part.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`') + '"'
                    for part in command)


def from_template(text: str, launcher: Path, folder: Path, icon: Path | None = None) -> str:
    """A Desktop Entry from one of the files in host/linux/ (the same files the Arch package installs): `Tessera.sh` in its Exec
    line becomes the launcher of this folder, the icon becomes the logo of this folder, and the entry runs in this folder."""
    lines = []
    for line in text.splitlines():
        if line.startswith('Exec='):
            words = line.removeprefix('Exec=').split()
            line = 'Exec=' + quote([str(launcher), *words[1:]] if words and words[0] == 'Tessera.sh' else words)
        elif line.startswith('Icon=') and icon is not None:
            line = f'Icon={icon}'
        lines.append(line)
        if line.startswith('Exec='):
            lines.append(f'Path={folder}')
    return '\n'.join(lines) + '\n'


def entry(command: list[str], folder: Path, icon: Path | None = None, comment: str = 'A DIY Stream Deck',
          hidden_start: bool = False) -> str:
    """The text of a Desktop Entry that runs `command` from `folder`."""
    exec_line = quote(command)
    lines = ['[Desktop Entry]', 'Type=Application', 'Name=Tessera', f'Comment={comment}', f'Exec={exec_line}',
             f'Path={folder}', 'Terminal=false', 'Categories=Utility;']
    if icon is not None:
        lines.append(f'Icon={icon}')
    if hidden_start:
        lines.append('X-GNOME-Autostart-enabled=true')
    return '\n'.join(lines) + '\n'


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(text, encoding='utf-8')
    os.replace(temporary, path)
    return path
