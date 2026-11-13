"""System tray app for Tessera: live status, profile switching, editor and host control.

Like the Stream Deck app it lives in the notification area, starts the USB host,
and opens the editor on a click.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from deck_control import ROOT, Controller, autostart_enabled, firmware_installing, save_profiles, set_autostart
from host_runtime import InstanceLock

log = logging.getLogger(__name__)

POLL_SECONDS = 2.0
COMMAND_PATH = ROOT / 'host/deck-command.local.json'
PROFILES_PATH = ROOT / 'host/profiles.json'
LOG_PATH = ROOT / 'host/deck.local.log'
FIRST_RUN_PATH = ROOT / 'host/tray-first-run.local.json'  # written once the Start with Windows question was asked
TROUBLE_SECONDS = 30  # how long a problem must last before the tray says so
PROBLEMS_PATH = ROOT / 'host/recent-problems.local.txt'
RESTART_WAITS = (5, 15, 60, 300)  # seconds before each automatic restart of a host that died; the last repeats
RESTART_RESET_SECONDS = 600  # a host that ran this long starts a new burst from the first wait
BRIGHTNESS_LEVELS = (100, 80, 60, 40, 20)
STATE_COLORS = {'connected': (53, 208, 127), 'waiting': (255, 183, 77), 'stopped': (255, 112, 112)}


def tray_state(status: dict) -> str:
    if not status.get('running'):
        return 'stopped'
    return 'connected' if status.get('device', {}).get('connected') else 'waiting'


def status_text(status: dict) -> str:
    state = tray_state(status)
    device = status.get('device', {})
    waiting = [name for name, agent in (('Claude', 'claude'), ('Codex', 'codex'), ('ZCode', 'zcode'))
               if status.get('agent_states', {}).get(agent) == 'waiting']
    suffix = f' · {", ".join(waiting)} waiting for you' if waiting else ''
    if state == 'connected':
        return f'Connected · {device.get("port")} · {device.get("profile")} / {device.get("page")}{suffix}'
    if state == 'waiting':
        return str(device.get('error') or 'Waiting for the panel …')[:110]
    return 'Host stopped'


def version_text(status: dict) -> str:
    """'Tessera 0.6.2 · panel 0.6.2': what helpers ask for first."""
    version_file = ROOT / 'VERSION'
    version = version_file.read_text(encoding='utf-8').strip() if version_file.is_file() else '?'
    firmware = status.get('device', {}).get('firmware')
    return f'Tessera {version}' + (f' · panel {firmware}' if firmware else '')


def trouble_text(status: dict) -> str | None:
    """The problem worth a notice when it lasts, or None."""
    if not status.get('running'):
        return 'The host is not running, so the panel does nothing. Start it from the tray menu.'
    error = status.get('device', {}).get('error')
    if not status.get('device', {}).get('connected') and error:
        return f'The panel is not connected: {error}'[:200]
    return None


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


_SWEEP = ((88, 224, 155), (83, 216, 190), (77, 208, 225), (128, 172, 240), (179, 136, 255))
STATUS_TILE = 2  # the top-right tile of the 3x3 mosaic shows the host status
TILE_COLORS = tuple(None if index == STATUS_TILE else _SWEEP[index // 3 + index % 3] for index in range(9))


def icon_tiles(size: int) -> list[tuple[int, int, int]]:
    """Top-left corner and edge length of the nine mosaic tiles for an icon of this size."""
    inset = 1
    gap = max(1, round(size * 0.06))
    tile = (size - 2 * inset - 2 * gap) // 3
    start = (size - (3 * tile + 2 * gap)) // 2
    return [(start + col * (tile + gap), start + row * (tile + gap), tile) for row in range(3) for col in range(3)]


def make_icon(state: str, size: int = 64) -> Image.Image:
    """The Tessera mark: a 3x3 mosaic on the brand gradient; the top-right tile shows the host status.

    Bold shapes only, so it stays readable when Windows scales it down to 16 px.
    """
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for color, (x, y, tile) in zip(TILE_COLORS, icon_tiles(size), strict=False):
        draw.rounded_rectangle((x, y, x + tile - 1, y + tile - 1), radius=max(1, tile // 4),
                               fill=(color or STATE_COLORS[state]) + (255,))
    return image


def set_brightness(level: int, path: Path = PROFILES_PATH) -> None:
    config = load_config(path)
    config['display'] = dict(config.get('display', {}), brightness=level)
    save_profiles(config, path)


def notifications_enabled(path: Path | None = None) -> bool:
    """Windows notifications the user did not ask for (panel connected, agents, timers); on unless switched off."""
    try:
        return load_config(path or PROFILES_PATH).get('notifications', True) is not False
    except (OSError, ValueError):
        return True


def set_notifications(enabled: bool, path: Path | None = None) -> None:
    config = load_config(path or PROFILES_PATH)
    config['notifications'] = enabled
    save_profiles(config, path or PROFILES_PATH)


class TrayApp:
    def __init__(self, controller: Controller | None = None):
        self.controller = controller or Controller()
        self.status: dict = {}
        self.state: str | None = None
        self.stop = threading.Event()
        self.last_notice = None  # newest notice already shown; the first poll only catches up
        self.host_work = threading.Lock()  # start, stop and restart of the host run one at a time
        self.menu_shows = None  # what the open menu was built from; it is rebuilt when this changes
        self.trouble = None  # (text, since, shown) of a problem that lasts
        self.user_stopped = False  # a host the user stopped is no problem to report
        self.seen_running = False  # only a host that ran is restarted by itself; a failed first start is reported
        self.restarts = 0  # automatic restarts in this burst
        self.restart_at = None  # when the next automatic restart runs (monotonic), while the host is down
        self.running_since = None  # since when the host has been seen running (monotonic)
        self.asked_autostart = FIRST_RUN_PATH.exists()  # the question waits for the first panel connection
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
        now = time.monotonic()
        if now - getattr(self, 'editor_asked', -10.0) < 2.0:  # a double click is one request
            return
        self.editor_asked = now
        pythonw = ROOT / 'host/.venv/Scripts/pythonw.exe'
        executable = str(pythonw if pythonw.is_file() else sys.executable)
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if os.name == 'nt' else 0
        subprocess.Popen([executable, str(ROOT / 'host/tessera_app.py'), '--editor'], cwd=ROOT, creationflags=flags)

    def host(self, *steps):
        """Run host steps one at a time. A second click while one runs is dropped: two starts made two hosts,
        and the second one died with 'Another Tessera host is already running'."""
        def work():
            if not self.host_work.acquire(blocking=False):
                return
            try:
                for step in steps:
                    step()
            finally:
                self.host_work.release()
        self.background(work)

    def warn(self, message):
        self.icon.notify(str(message)[:200], 'Tessera')

    def start_host(self, *_):
        self.user_stopped = False
        self.host(lambda: self.controller.start(warn=self.warn))

    def stop_host(self, *_):
        self.user_stopped = True
        self.host(self.controller.stop)

    def restart_host(self, *_):
        self.host(self.controller.stop, lambda: self.controller.start(warn=self.warn))

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

    def toggle_notifications(self, *_):
        self.background(lambda: set_notifications(not notifications_enabled()))

    def tell(self, message, title='Tessera'):
        """A notice the user did not click for: kept quiet when notifications are off. Answers to a click use notify."""
        if notifications_enabled():
            self.icon.notify(message, title)

    # --- help: what a user needs to report a problem ---------------------------
    def open_log(self, *_):
        if LOG_PATH.is_file():
            os.startfile(LOG_PATH)  # noqa: S606 - the user's own log in their text editor
        else:
            self.icon.notify('There is no host log yet. It is written once the host has run.', 'Tessera')

    def show_problems(self, *_):
        """The last failures from the log in a small text file, so a user need not read the whole log."""
        import diagnostics
        problems = diagnostics.recent_problems(LOG_PATH)
        if not problems:
            self.icon.notify('No problems in the host log.', 'Tessera')
            return
        PROBLEMS_PATH.write_text('Recent problems in the Tessera host log (newest last)\n\n' + '\n'.join(problems) + '\n',
                                 encoding='utf-8')
        os.startfile(PROBLEMS_PATH)  # noqa: S606 - our own text file in the user's text editor

    def save_diagnostics(self, *_):
        def work():
            import setup_tool
            path = setup_tool.diagnostics()
            subprocess.Popen(['explorer', '/select,', str(path)])  # noqa: S603,S607
            self.icon.notify(f'Saved {path.name}. User names and credentials are left out.', 'Tessera')
        self.background(work)

    def open_data_folder(self, *_):
        os.startfile(ROOT / 'host')  # noqa: S606 - profiles, icons and backups live here

    def check_for_updates(self, *_):
        def work():
            import updates
            current = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
            release = updates.check(current)
            if release.get('newer'):
                notes = release.get('notes') or 'Open the editor: Panel → Panel firmware and updates …'
                self.icon.notify(notes[:250], f"Update available: {release['latest']}")
            else:
                self.icon.notify(f'Tessera {current} is the newest version.', 'Tessera')
        self.background(work)

    def ask_about_autostart(self):
        """Once, at the first panel connection: the panel does nothing after a restart until Tessera runs, so ask."""
        if FIRST_RUN_PATH.exists() or os.name != 'nt':
            return
        write_command({'asked': 'autostart'}, FIRST_RUN_PATH)
        if autostart_enabled():
            return
        import ctypes
        answer = ctypes.windll.user32.MessageBoxW(
            None, 'Start Tessera when you sign in to Windows?\n\nThe panel then works after every restart. '
                  'You can change this later in the tray menu: Start with Windows.', 'Tessera', 0x4 | 0x20 | 0x10000 | 0x40000)
        if answer == 6:  # IDYES
            set_autostart(True)

    def quit(self, *_):
        self.stop.set()
        self.icon.stop()

    def quit_and_stop_host(self, *_):
        self.background(self._stop_then_quit)

    def _stop_then_quit(self):
        self.user_stopped = True
        with self.host_work:
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
        flashing = firmware_installing()  # a host started now would take the COM port from the flash
        yield pystray.MenuItem('Installing panel firmware …' if flashing and not running else status_text(self.status),
                               None, enabled=False)
        yield pystray.MenuItem(version_text(self.status), None, enabled=False)
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem('Open editor', self.open_editor, default=True)
        yield pystray.MenuItem('Profiles', pystray.Menu(self.profile_items), enabled=running)
        yield pystray.MenuItem('Brightness', pystray.Menu(self.brightness_items))
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem('Start host', self.start_host, enabled=not running and not flashing)
        yield pystray.MenuItem('Restart host', self.restart_host, enabled=running)
        yield pystray.MenuItem('Stop host', self.stop_host, enabled=running)
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem('Start with Windows', self.toggle_autostart, checked=lambda item: autostart_enabled())
        yield pystray.MenuItem('Show notifications', self.toggle_notifications, checked=lambda item: notifications_enabled())
        yield pystray.MenuItem('Help', pystray.Menu(
            pystray.MenuItem('Open the host log', self.open_log),
            pystray.MenuItem('Recent problems', lambda *_: self.background(self.show_problems)),
            pystray.MenuItem('Save diagnostics for a bug report', self.save_diagnostics),
            pystray.MenuItem('Open the data folder', self.open_data_folder),
            pystray.MenuItem('Check for updates', self.check_for_updates)))
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem('Quit tray', self.quit)
        yield pystray.MenuItem('Quit and stop host', self.quit_and_stop_host)

    # --- status polling ---------------------------------------------------------
    def refresh(self):
        self.status = self.controller.status()
        state = tray_state(self.status)
        self.icon.title = f'Tessera — {status_text(self.status)}'[:120]  # Windows allows 127 characters in a tooltip
        shown = (status_text(self.status), bool(self.status.get('running')), self.status.get('device', {}).get('profile'),
                 PROFILES_PATH.stat().st_mtime_ns if PROFILES_PATH.exists() else 0, firmware_installing())
        if shown != self.menu_shows:  # the menu is built once; without this it keeps the old status and ticks
            self.menu_shows = shown
            self.icon.update_menu()
        self.show_notices(self.status.get('notices', []))
        self.watch_host(bool(self.status.get('running')), time.monotonic())
        self.report_trouble(trouble_text(self.status), time.monotonic())
        if state != self.state:
            previous, self.state = self.state, state
            self.icon.icon = make_icon(state)
            if state == 'connected' and not self.asked_autostart:
                # the first connection ever: say what comes next, then ask about autostart now that it works
                self.asked_autostart = True
                self.tell('Panel connected. Open the editor to set up your keys.', 'Tessera')
                self.background(self.ask_about_autostart)
            elif previous == 'connected':
                self.tell('The panel was disconnected.', 'Tessera')
            elif previous and state == 'connected':
                self.tell('The panel is connected.', 'Tessera')

    def watch_host(self, running, now):
        """Start a host again that died without the user pressing Stop: after 5 s, 15 s, 60 s, then every 5 min.
        One notice per burst; a host that then runs RESTART_RESET_SECONDS starts the next burst afresh."""
        if running:
            self.seen_running, self.restart_at = True, None
            if self.running_since is None:
                self.running_since = now
            elif now - self.running_since >= RESTART_RESET_SECONDS:
                self.restarts = 0
            return
        self.running_since = None
        # Stop, Restart (while it runs) and a firmware install stop the host on purpose
        if self.user_stopped or not self.seen_running or self.host_work.locked() or firmware_installing():
            self.restart_at = None
            return
        if self.restart_at is None:
            if self.restarts == 0:
                self.tell('The host stopped unexpectedly. Tessera starts it again in a moment.', 'Tessera')
            self.restart_at = now + RESTART_WAITS[min(self.restarts, len(RESTART_WAITS) - 1)]
        elif now >= self.restart_at:
            self.restarts += 1
            self.host(self.restart_quietly)

    def restart_quietly(self):
        try:
            self.controller.start(warn=self.warn)
        except Exception:  # the burst notice said it; the next attempt follows the backoff
            log.debug('automatic host start failed', exc_info=True)
        finally:
            self.restart_at = None  # the next poll waits again if this start did not keep the host up

    def report_trouble(self, text, now):
        """One notice for a problem that lasts TROUBLE_SECONDS (a port held by another program, a host that
        stopped); the icon colour alone does not say why nothing works. A new problem gets a new notice."""
        # the editor stops the host for a firmware install, which takes longer than TROUBLE_SECONDS
        # a host that is being restarted already got its notice
        if (text is None or (not self.status.get('running') and (self.user_stopped or self.restart_at is not None))
                or firmware_installing()):
            self.trouble = None
            return
        if self.trouble is None or self.trouble[0] != text:
            self.trouble = (text, now, False)
        elif not self.trouble[2] and now - self.trouble[1] >= TROUBLE_SECONDS:
            self.tell(text, 'Tessera')
            self.trouble = (text, self.trouble[1], True)

    def show_notices(self, notices):
        ids = [item['id'] for item in notices if isinstance(item.get('id'), int)]
        if self.last_notice is None:
            self.last_notice = max(ids, default=0)
            return
        for item in notices:
            if isinstance(item.get('id'), int) and item['id'] > self.last_notice:
                self.tell(str(item.get('message', '')), str(item.get('title', 'Tessera')))
        self.last_notice = max([self.last_notice, *ids])

    def poll(self):
        wait = 0.3  # the first look comes at once, so the icon does not start as 'stopped'
        while not self.stop.wait(wait):
            wait = POLL_SECONDS
            try:
                self.refresh()
            except Exception:
                log.debug('tray refresh failed', exc_info=True)

    def run(self):
        self.start_host()
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
