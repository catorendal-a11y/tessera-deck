"""Installed programs on Linux: the .desktop entries of the application menu, their icons, and starting them.

The same jobs as the Start menu scan and the icon extraction on Windows. A program's `target` is the path of its
.desktop file; the process name that profiles match (`firefox`) comes from its Exec line.
"""
from __future__ import annotations

import configparser
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from platform_linux.desktop_entries import data_home

IGNORED_WORDS = ('uninstall', 'readme', 'documentation', 'manual', 'release notes', 'support')
FIELD_CODES = re.compile(r'%[a-zA-Z%]')
WRAPPERS = ('env', 'nohup', 'setsid', 'exec', 'sudo', 'pkexec')
ICON_SIZES = (512, 256, 192, 128, 96, 64, 48, 'scalable')
LAUNCH_TIMEOUT = 10


def data_dirs(environ=None) -> list[Path]:
    environ = os.environ if environ is None else environ
    system = (environ.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share').split(':')
    return [data_home(environ)] + [Path(item) for item in system if item]


def parse(path: Path) -> dict | None:
    """The fields of a .desktop file that matter here, or None when it is not a program to show."""
    parser = configparser.RawConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    try:
        parser.read(path, encoding='utf-8')
        entry = parser['Desktop Entry']
    except (OSError, UnicodeDecodeError, configparser.Error, KeyError):
        return None
    if entry.get('Type', 'Application') != 'Application' or not entry.get('Exec'):
        return None
    if entry.get('NoDisplay', '').lower() == 'true' or entry.get('Hidden', '').lower() == 'true':
        return None
    language = (os.environ.get('LANG') or '').split('.')[0]
    name = entry.get(f'Name[{language}]') or entry.get(f'Name[{language.split("_")[0]}]') or entry.get('Name', '')
    return {'name': name.strip(), 'exec': entry['Exec'], 'icon': entry.get('Icon', ''),
            'terminal': entry.get('Terminal', '').lower() == 'true'}


def scan(environ=None) -> list[dict]:
    """[{'name', 'target'}] for the programs of the application menu, sorted by name."""
    programs = {}
    for base in data_dirs(environ):
        folder = base / 'applications'
        if not folder.is_dir():
            continue
        try:
            files = sorted(folder.rglob('*.desktop'))
        except OSError:
            continue
        for path in files:
            info = parse(path)
            if not info or not info['name']:
                continue
            key = info['name'].casefold()
            if any(word in key for word in IGNORED_WORDS) or key in programs:
                continue  # the user's own entries come first and win over the system ones
            programs[key] = {'name': info['name'], 'target': str(path)}
    return sorted(programs.values(), key=lambda item: item['name'].casefold())


def process_name(exec_line: str) -> str:
    """The program a menu entry runs, as the host sees processes: firefox, not `env VAR=1 /usr/bin/firefox %u`."""
    try:
        words = shlex.split(FIELD_CODES.sub('', exec_line))
    except ValueError:
        return ''
    while words:
        word = words[0]
        if os.path.basename(word) in ('sh', 'bash') and len(words) > 2 and words[1] == '-c':
            return process_name(words[2])  # sh -c "exec spotify": the command inside
        if os.path.basename(word) in WRAPPERS or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*', word) or word.startswith('-'):
            words.pop(0)
            continue
        if os.path.basename(word) == 'flatpak' and 'run' in words:  # flatpak run [options] org.mozilla.firefox
            rest = [item for item in words[words.index('run') + 1:] if not item.startswith('-')]
            return rest[0].rsplit('.', 1)[-1].lower() if rest else ''
        return os.path.basename(word).lower()
    return ''


def describe(target: str) -> dict:
    """{'name', 'process'} of a program picked from the list; ValueError when it is not a .desktop entry."""
    info = parse(Path(target)) if target.endswith('.desktop') else None
    if info is None:
        raise ValueError('Choose a program of the application menu')
    return {'name': info['name'], 'process': process_name(info['exec'])}


def icon_file(name: str, environ=None) -> Path | None:
    """The image file for an Icon= value: a path, or the best file of the icon themes (PNG first, then SVG)."""
    if not name:
        return None
    if name.startswith('/'):
        return Path(name) if Path(name).is_file() else None
    bases = [base / 'icons' for base in data_dirs(environ)] + [Path.home() / '.icons']
    themes = ('hicolor', 'Adwaita', 'gnome', 'breeze', 'Papirus')
    found = []
    for base in bases:
        for theme in themes:
            for size in ICON_SIZES:
                folder = f'{size}x{size}' if size != 'scalable' else 'scalable'
                for extension in ('png', 'svg'):
                    path = base / theme / folder / 'apps' / f'{name}.{extension}'
                    if path.is_file():
                        found.append((size if isinstance(size, int) else 1, extension != 'png', path))
    for base in (Path('/usr/share/pixmaps'),):
        for extension in ('png', 'svg', 'xpm'):
            if (base / f'{name}.{extension}').is_file():
                found.append((0, extension != 'png', base / f'{name}.{extension}'))
    if not found:
        return None
    # a PNG of 128 px or more is crisp enough; otherwise the largest PNG, otherwise a vector icon
    pngs = [item for item in found if not item[1]]
    if pngs:
        return max(pngs, key=lambda item: item[0])[2]
    return found[0][2]


def icon_image(target: str, size: int = 256):
    """A PIL image of the program's icon; raises OSError/ValueError when there is none."""
    from PIL import Image
    info = parse(Path(target))
    if info is None:
        raise ValueError('Choose a program of the application menu')
    path = icon_file(info['icon'])
    if path is None:
        raise ValueError('The program has no icon file')
    if path.suffix.lower() == '.svg':
        converter = shutil.which('rsvg-convert')
        if converter is None:
            raise ValueError('A vector icon needs rsvg-convert (librsvg) to be drawn')
        done = subprocess.run([converter, '-w', str(size), '-h', str(size), str(path)], capture_output=True, timeout=10)
        if done.returncode != 0:
            raise OSError('The icon could not be drawn')
        from io import BytesIO
        return Image.open(BytesIO(done.stdout)).convert('RGBA')
    return Image.open(path).convert('RGBA')


def launch(target: str) -> None:
    """Start a program (.desktop entry, file or folder) or open an address, without waiting for it."""
    if target.endswith('.desktop') and Path(target).is_file():
        command = ['gio', 'launch', target] if shutil.which('gio') else ['gtk-launch', Path(target).stem]
    else:
        target = target if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target) else os.path.expanduser(os.path.expandvars(target))
        command = ['xdg-open', target]
    if shutil.which(command[0]) is None:
        raise OSError(f'{command[0]} is not installed')
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def script_command(script: str):
    """The command that runs a script file (the interpreters Linux has)."""
    from platform_linux import scripts
    return scripts.command(script)


def locate(target: str, *_, **__) -> None:
    """Windows finds a program that moved; the application menu does not need that here."""
    return None
