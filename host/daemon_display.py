"""Backlight, dimming, quiet hours and the ambient clock screen of the panel."""
import json
from pathlib import Path
import time

from config_check import in_quiet_hours
from control_api import NOTIFY_MAX_TEXT

DEFAULT_DIM_AFTER = 300  # seconds of no presses before the panel dims


def banner_text(text) -> str:
    """Any text as the banner takes it: one line of printable characters, at most NOTIFY_MAX_TEXT, cut with an ellipsis.
    The firmware holds 400 bytes, so 99 characters and the 3-byte ellipsis always fit. The panel fonts have no arrow,
    so a menu path such as 'More → Plugins' becomes 'More > Plugins'."""
    text = str(text).replace('→', '>')
    line = ' '.join(''.join(char for char in text if char.isprintable() or char.isspace()).split())
    return line if len(line) <= NOTIFY_MAX_TEXT else line[:NOTIFY_MAX_TEXT - 1].rstrip() + '…'


def windows_clock() -> str:
    """'12h' when Windows shows the time with AM/PM (Region settings), else '24h'."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Control Panel\International') as key:
            return '12h' if str(winreg.QueryValueEx(key, 'iTime')[0]) == '0' else '24h'
    except (ImportError, OSError):
        return '24h'


class DisplayMixin:
    """Methods of the Daemon; they use its state."""

    def display_settings(self):
        display = self.config.get('display', {})
        return {'brightness': display.get('brightness', 100),
                'dim_after': display.get('dim_after', DEFAULT_DIM_AFTER),
                'dim_level': display.get('dim_level', 10), 'night': display.get('night')}

    def minute_of_day(self):
        now = time.localtime()
        return now.tm_hour * 60 + now.tm_min

    def wanted_brightness(self):
        settings = self.display_settings()
        night = settings['night']
        return night['brightness'] if in_quiet_hours(night, self.minute_of_day()) else settings['brightness']

    def apply_brightness(self):
        self.sent_brightness = self.wanted_brightness()
        self.panel.send_line(f'AD_BRIGHTNESS {self.sent_brightness}')
        self.dimmed = False

    def save_panel_brightness(self, level):
        """The panel's about-sheet slider set a level: keep it as the setting in force now (the night one in quiet
        hours), so the host does not send the old level back on the next connect."""
        from deck_control import save_profiles  # deck_control imports this daemon
        path = Path(self.args.profiles)
        config = json.loads(path.read_text(encoding='utf-8'))
        display = dict(config.get('display', {}))
        night = display.get('night')
        if in_quiet_hours(night, self.minute_of_day()):
            display['night'] = dict(night, brightness=level)
        else:
            display['brightness'] = level
        config['display'] = display
        save_profiles(config, path)
        self.sent_brightness = level

    def clock_format(self):
        """'12h' or '24h' for the panel's clocks: the Display setting, or the format Windows uses."""
        choice = self.config.get('display', {}).get('clock', 'auto')
        return choice if choice in ('12h', '24h') else windows_clock()

    def brightness_tick(self):
        """Quiet hours: change the brightness when the clock enters or leaves the night window."""
        if self.panel is None or self.dimmed or self.sent_brightness is None:
            return
        if self.wanted_brightness() != self.sent_brightness:
            self.enqueue(('brightness',))

    def wake_display(self):
        self.last_activity = time.monotonic()
        self.leave_ambient()
        if self.dimmed:
            self.log('Panel woke')
        self.dimmed = False
        self.panel.send_line('AD_SCREEN deck')  # a wake always shows the screen under the clock
        self.panel.send_line('AD_DISPLAY_WAKE')

    def dim_display(self, reason):
        self.panel.send_line(f'AD_DISPLAY_DIM {self.display_settings()["dim_level"]}')
        self.dimmed = True
        self.log(f'Panel dimmed {reason}')

    def lock_tick(self, locked):
        """Dim when Windows locks and wake on unlock; only when auto-dim is enabled."""
        if locked == self.locked:
            return
        self.locked = locked
        if self.panel is None or not self.display_settings()['dim_after']:
            return
        if locked and not self.dimmed:
            self.dim_display('because Windows is locked')
        elif not locked and self.dimmed:
            self.wake_display()

    def panel_notice(self, text, level, seconds):
        """A short message on the panel's banner. False when no panel is connected, its firmware has no banner
        ("notify":1 in get_info) or it did not take the line."""
        panel, banner = self.panel, self.device_info.get('notify')
        if panel is None or self.connection_failed.is_set() or type(banner) is not int or banner < 1:
            return False
        # The control API checked the text; a newline would still end the line early, so it never gets through.
        line = ''.join(char if char.isprintable() else ' ' for char in str(text))
        try:
            panel.send_line(f'AD_NOTIFY {level} {int(seconds)} {line}')
            return True
        except OSError as exc:
            self.log(f'The panel did not take the message: {exc}')
            return False

    def show_notice(self, text, level, seconds):
        """A short message (deckctl say, POST /v1/notify) on the panel's banner, or as a Windows notification through
        the tray when the panel cannot show it."""
        if not self.panel_notice(text, level, seconds):
            self.notify('Tessera', text)

    def question_open(self):
        permissions = getattr(self, 'permissions', None)
        return bool(permissions and permissions.current())

    def ambient_settings(self):
        return dict({'enabled': False, 'after': 120}, **self.config.get('ambient', {}))

    def leave_ambient(self):
        # sent even when the host thinks the keys show: a touch's 'screen-deck' can cross the host's 'ambient'
        if (self.ambient_active or self.ambient_requested) and self.panel is not None:
            self.panel.send_line('AD_SCREEN deck')
        self.ambient_active = False
        self.ambient_requested = False
        self.ambient_sent = ''

    def show_screen(self, show):
        """The screen action: the clock or the keys on demand, whether or not the idle clock is switched on."""
        if self.panel is None:
            raise ValueError('The panel is not connected')
        if (self.device_info.get('protocol') or 1) < 3:
            raise ValueError('The panel firmware does not have the clock screen; update it first')
        if show == 'toggle':
            show = 'keys' if self.ambient_active else 'clock'
        if show == 'keys':
            self.leave_ambient()
            return
        self.ambient_active = self.ambient_requested = True
        self.ambient_sent = ''
        self.panel.send_line('AD_SCREEN ambient')

    def ambient_tick(self, now):
        """Show the ambient clock after `after` idle seconds and keep its weather line fresh."""
        settings = self.ambient_settings()
        supported = (self.device_info.get('protocol') or 1) >= 3
        if self.panel is None or not supported or not (settings['enabled'] or self.ambient_requested):
            if self.ambient_active:
                self.leave_ambient()
            return
        if not self.ambient_active:
            if self.locked or now - self.last_activity < settings['after'] or self.question_open():
                return
            self.ambient_active = True
            self.panel.send_line('AD_SCREEN ambient')
            self.log('Ambient screen shown')
        line = self.weather.line(settings)
        if line != self.ambient_sent:
            self.panel.send_line('AD_AMBIENT ' + line)
            self.ambient_sent = line

    def idle_tick(self, now):
        """Dim the panel once after dim_after seconds without a press."""
        settings = self.display_settings()
        if (not settings['dim_after'] or self.dimmed or self.panel is None or self.question_open()
                or now - self.last_activity < settings['dim_after']):
            return
        self.dim_display(f'after {settings["dim_after"]} s without a press')
