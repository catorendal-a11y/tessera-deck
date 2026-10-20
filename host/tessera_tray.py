"""System tray app for Tessera: live status, profile switching, editor and host control.

Like the Stream Deck app it lives in the notification area, starts the USB host,
and opens the editor on a click.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from deck_control import ROOT, Controller, autostart_enabled, save_profiles, set_autostart
from host_runtime import InstanceLock

POLL_SECONDS = 2.0
COMMAND_PATH = ROOT / 'host/deck-command.local.json'
PROFILES_PATH = ROOT / 'host/profiles.json'
BRIGHTNESS_LEVELS = (100, 80, 60, 40, 20)
STATE_COLORS = {'connected': (53, 208, 127), 'waiting': (255, 183, 77), 'stopped': (255, 112, 112)}


def tray_state(status: dict) -> str:
    if not status.get('running'):
        return 'stopped'
    return 'connected' if status.get('device', {}).get('connected') else 'waiting'


def status_text(status: dict) -> str:
    state = tray_state(status)
    device = status.get('device', {})
    if state == 'connected':
        return f'Connected · {device.get("port")} · {device.get("profile")} / {device.get("page")}'
    if state == 'waiting':
        return 'Waiting for the panel …'
    return 'Host stopped'


def load_config(path: Path = PROFILES_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def command_for_profile(config: dict, name: str) -> dict:
    """The host command that shows a profile's first page."""
    profile = config['profiles'][name]
    return {'profile': name, 'page': next(iter(profile['pages']))}


def write_command(command: dict, path: Path = COMMAND_PATH) -> None:
    temporary = Path(path).with_suffix('.tmp')
    temporary.write_text(json.dumps(command), encoding='utf-8')
    os.replace(temporary, path)


def make_icon(state: str, size: int = 64) -> Image.Image:
    """A small deck grid with a status dot in the corner."""
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, size - 3, size - 3), radius=size // 6, fill=(23, 35, 41, 255),
                           outline=(88, 224, 155, 255), width=max(2, size // 22))
    cell, gap, margin = size // 6, size // 14, size // 5
    for row in range(3):
        for column in range(3):
            x = margin + column * (cell + gap)
            y = margin + row * (cell + gap)
            draw.rounded_rectangle((x, y, x + cell, y + cell), radius=max(1, cell // 4), fill=(232, 244, 239, 255))
    radius = size // 5
    draw.ellipse((size - 2 * radius - 1, size - 2 * radius - 1, size - 1, size - 1),
                 fill=STATE_COLORS[state] + (255,), outline=(9, 16, 20, 255), width=max(2, size // 24))
    return image


def set_brightness(level: int, path: Path = PROFILES_PATH) -> None:
    config = load_config(path)
    config['display'] = dict(config.get('display', {}), brightness=level)
    save_profiles(config, path)


class TrayApp:
    def __init__(self, controller: Controller | None = None):
        self.controller = controller or Controller()
        self.status: dict = {}
        self.state: str | None = None
        self.stop = threading.Event()
        self.icon = pystray.Icon('tessera', make_icon('stopped'), 'Tessera',
                                 menu=pystray.Menu(self.menu_items))

    # --- actions (all run off the UI thread) ---------------------------------
    def background(self, work, *args):
        threading.Thread(target=self._guarded, args=(work, *args), daemon=True).start()

    def _guarded(self, work, *args):
        try:
            work(*args)
        except Exception as exc:  # surfaced as a tray notification, never a crash
            self.icon.notify(str(exc)[:200], 'Tessera')

    def open_editor(self, *_):
        pythonw = ROOT / 'host/.venv/Scripts/pythonw.exe'
        executable = str(pythonw if pythonw.is_file() else sys.executable)
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if os.name == 'nt' else 0
        subprocess.Popen([executable, str(ROOT / 'host/tessera_app.py'), '--editor'], cwd=ROOT, creationflags=flags)

    def start_host(self, *_):
        self.background(self.controller.start)

    def stop_host(self, *_):
        self.background(self.controller.stop)

    def restart_host(self, *_):
        self.background(lambda: (self.controller.stop(), self.controller.start()))

    def switch_profile(self, name):
        def action(*_):
            write_command(command_for_profile(load_config(), name))
        return action

    def choose_brightness(self, level):
        def action(*_):
            self.background(set_brightness, level)
        return action

    def toggle_autostart(self, *_):
        self.background(lambda: set_autostart(not autostart_enabled()))

    def quit(self, *_):
        self.stop.set()
        self.icon.stop()

    def quit_and_stop_host(self, *_):
        self.background(self._stop_then_quit)

    def _stop_then_quit(self):
        self.controller.stop()
        self.quit()

    # --- menu -----------------------------------------------------------------
    def profile_items(self):
        try:
            config = load_config()
        except (OSError, ValueError):
            return
        current = self.status.get('device', {}).get('profile')
        for name in config['profiles']:
            yield pystray.MenuItem(name, self.switch_profile(name), checked=lambda item, n=name: n == current,
                                   radio=True)

    def brightness_items(self):
        try:
            current = load_config().get('display', {}).get('brightness', 100)
        except (OSError, ValueError):
            current = 100
        for level in BRIGHTNESS_LEVELS:
            yield pystray.MenuItem(f'{level}%', self.choose_brightness(level),
                                   checked=lambda item, v=level: v == current, radio=True)

    def menu_items(self):
        running = bool(self.status.get('running'))
        yield pystray.MenuItem(status_text(self.status), None, enabled=False)
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem('Open editor', self.open_editor, default=True)
        yield pystray.MenuItem('Profiles', pystray.Menu(self.profile_items), enabled=running)
        yield pystray.MenuItem('Brightness', pystray.Menu(self.brightness_items))
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem('Start host', self.start_host, enabled=not running)
        yield pystray.MenuItem('Restart host', self.restart_host, enabled=running)
        yield pystray.MenuItem('Stop host', self.stop_host, enabled=running)
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem('Start with Windows', self.toggle_autostart, checked=lambda item: autostart_enabled())
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem('Quit tray', self.quit)
        yield pystray.MenuItem('Quit and stop host', self.quit_and_stop_host)

    # --- status polling ---------------------------------------------------------
    def refresh(self):
        self.status = self.controller.status()
        state = tray_state(self.status)
        self.icon.title = f'Tessera — {status_text(self.status)}'
        if state != self.state:
            previous, self.state = self.state, state
            self.icon.icon = make_icon(state)
            if previous == 'connected':
                self.icon.notify('The panel was disconnected.', 'Tessera')
            elif previous and state == 'connected':
                self.icon.notify('The panel is connected.', 'Tessera')

    def poll(self):
        while not self.stop.wait(POLL_SECONDS):
            try:
                self.refresh()
            except Exception:
                continue

    def run(self):
        self.background(self.controller.start)
        threading.Thread(target=self.poll, daemon=True).start()
        self.icon.run()


def main():
    lock = InstanceLock(Path(__file__).with_name('deck-tray.local.lock'))
    if not lock.acquire():
        print('The Tessera tray is already running.')
        return
    try:
        TrayApp().run()
    finally:
        lock.release()


if __name__ == '__main__':
    main()
