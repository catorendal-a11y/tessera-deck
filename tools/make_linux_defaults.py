"""Make host/profiles.default.linux.json from host/profiles.default.json.

The Windows default is full of Windows shortcuts (win+..., ms-settings:, sndvol.exe, PowerToys). This keeps every page
and slot, and swaps each Windows-only key for the Linux equivalent or removes it. Run it again after the Windows default
changes:  python tools/make_linux_defaults.py
"""
import copy
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def shell(command):
    return {'type': 'shell', 'command': command, 'timeout': 10}


def none_installed(names):
    """What the chain says when nothing in it is installed; the key's error shows this instead of a bare exit code 1.
    It names each program once, without its arguments ('gnome-control-center sound' is gnome-control-center)."""
    programs = ', '.join(dict.fromkeys(name.split()[0] for name in names))
    return f"{{ echo 'None of these programs is installed: {programs}. Install one with your package manager.' >&2; exit 1; }}"


def launch(*programs):
    """Start the first installed program of the list, detached, so the key returns at once."""
    chain = ' || '.join(f'(command -v {name.split()[0]} >/dev/null 2>&1 && exec setsid -f {name})' for name in programs)
    return shell(f'{chain} || {none_installed(programs)}')


# Each terminal with the option after which it takes the command to run. Ptyxis is the default on Fedora 41 and later,
# kgx (GNOME Console) on GNOME without gnome-terminal, mate-terminal on MATE, qterminal on LXQt and cosmic-term on COSMIC.
TERMINALS = (('x-terminal-emulator', '-e'), ('gnome-terminal', '--'), ('ptyxis', '--'), ('kgx', '--'), ('konsole', '-e'),
             ('xfce4-terminal', '-x'), ('mate-terminal', '-x'), ('qterminal', '-e'), ('cosmic-term', '-e'), ('xterm', '-e'))
# --new-window: Ptyxis opens a new window when one is already open, as the other terminals do
TERMINAL = launch(*(f'{name} --new-window' if name == 'ptyxis' else name for name, _ in TERMINALS))
SETTINGS = launch('cinnamon-settings', 'gnome-control-center', 'systemsettings', 'xfce4-settings-manager')
MIXER = launch('pavucontrol', 'pavucontrol-qt', 'gnome-control-center sound', 'systemsettings kcm_pulseaudio')
CHANGES = {
    ('main', 'Explorer'): ('Files', [{'type': 'open', 'target': '~'}]),
    ('main', 'Terminal'): (None, [TERMINAL]),
    ('main', 'Calculator'): (None, [launch('gnome-calculator', 'kcalc', 'galculator', 'xcalc')]),
    ('main', 'Screenshot'): (None, [{'type': 'hotkey', 'keys': 'printscreen'}]),
    ('main', 'Lock PC'): (None, [shell('loginctl lock-session')]),
    ('system', 'Lock PC'): (None, [shell('loginctl lock-session')]),
    ('system', 'Task view'): None,
    ('system', 'Search'): (None, [{'type': 'hotkey', 'keys': 'win'}]),
    ('system', 'Notifications'): None,
    ('system', 'Quick settings'): None,
    ('system', 'Maximize'): (None, [{'type': 'window', 'op': 'maximize'}]),
    ('system', 'Minimize'): (None, [{'type': 'window', 'op': 'minimize'}]),
    ('system', 'Prev desktop'): (None, [{'type': 'hotkey', 'keys': 'ctrl+alt+left'}]),
    ('system', 'Next desktop'): (None, [{'type': 'hotkey', 'keys': 'ctrl+alt+right'}]),
    ('system', 'New desktop'): None,
    ('system', 'Close desktop'): None,
    ('system', 'To left screen'): (None, [{'type': 'window', 'op': 'next_monitor'}]),
    ('system', 'To right screen'): None,
    ('audio', 'Sound settings'): (None, [launch('cinnamon-settings sound', 'gnome-control-center sound', 'systemsettings kcm_pulseaudio', 'pavucontrol')]),
    ('audio', 'Volume mixer'): (None, [MIXER]),
    ('audio', 'Audio devices'): (None, [MIXER]),
    ('audio', 'Bluetooth'): (None, [launch('blueman-manager', 'cinnamon-settings bluetooth', 'gnome-control-center bluetooth', 'systemsettings kcm_bluetooth')]),
    ('audio', 'Quick settings'): None,
    ('tools', 'Screenshot'): (None, [{'type': 'hotkey', 'keys': 'printscreen'}]),
    ('tools', 'Clipboard'): None,
    ('tools', 'Emoji'): None,
    ('tools', 'Color picker'): None,
    ('tools', 'OCR text'): None,
    ('tools', 'Always on top'): (None, [{'type': 'window', 'op': 'topmost'}]),
    ('tools', 'Calculator'): (None, [launch('gnome-calculator', 'kcalc', 'galculator', 'xcalc')]),
    ('tools', 'Notepad'): ('Editor', [launch('gnome-text-editor', 'gedit', 'kate', 'xed', 'mousepad')]),
    ('tools', 'Task Manager'): ('System monitor', [launch('gnome-system-monitor', 'plasma-systemmonitor', 'ksysguard', 'xfce4-taskmanager')]),
    ('tools', 'Settings'): (None, [SETTINGS]),
    ('tools', 'PowerToys Run'): None,
    ('tools', 'Plain paste'): (None, [{'type': 'hotkey', 'keys': 'ctrl+shift+v'}]),
    ('tools', 'Snap layouts'): None,
    ('tools', 'Workspaces'): None,
}


# The agent profiles start their tool in Windows Terminal: start "" wt.exe -w 0 nt -d "%CD%" cmd.exe /k claude -c
WINDOWS_TERMINAL = re.compile(r'^start "" wt\.exe -w 0 nt -d "%CD%" cmd\.exe /k (?P<command>.+)$')
ZCODE_EXE = re.compile(r'^start "" "%LOCALAPPDATA%\\Programs\\ZCode\\ZCode\.exe"$')


def in_terminal(command):
    """Open the first available terminal emulator in the home folder and run `command` in it, detached."""
    chain = ' || '.join(f'(command -v {name} >/dev/null 2>&1 && exec setsid -f {name} {flag} {command})' for name, flag in TERMINALS)
    return {'type': 'shell', 'command': f'cd "$HOME" && ({chain} || {none_installed([name for name, _ in TERMINALS])})', 'timeout': 10}


def linux_action(action):
    """An action with its Windows-only shell command swapped; anything else is returned as it is."""
    if action.get('type') == 'shell':
        match = WINDOWS_TERMINAL.match(action.get('command', ''))
        if match:
            return in_terminal(match['command'])
        if ZCODE_EXE.match(action.get('command', '')):
            return launch('zcode')
    return action


def convert(config):
    config = copy.deepcopy(config)
    for profile in config['profiles'].values():
        for name, buttons in profile['pages'].items():
            kept = []
            for button in buttons:
                change = CHANGES.get((name, button.get('label')), False)
                if change is None:
                    continue  # no Linux equivalent: the slot stays empty
                if change:
                    label, actions = change
                    button['actions'] = actions
                    button['label'] = label or button['label']
                    if button.get('icon') == 'app':
                        button['icon'] = 'lc:e0f5' if name == 'main' else button['icon']
                kept.append(button)
            for button in kept:
                button['actions'] = [linux_action(action) for action in button.get('actions', [])]
                for state in button.get('states', []):
                    state['actions'] = [linux_action(action) for action in state.get('actions', [])]
            profile['pages'][name] = kept
    return config


def main():
    source = ROOT / 'host/profiles.default.json'
    target = ROOT / 'host/profiles.default.linux.json'
    text = json.dumps(convert(json.loads(source.read_text(encoding='utf-8'))), indent=2, ensure_ascii=False) + '\n'
    target.write_text(text, encoding='utf-8')
    print(f'Wrote {target}')


if __name__ == '__main__':
    sys.exit(main())
