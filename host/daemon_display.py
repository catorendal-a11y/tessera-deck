"""Backlight, dimming, quiet hours and the ambient clock screen of the panel."""
import time

from config_check import in_quiet_hours

DEFAULT_DIM_AFTER = 300  # seconds of no presses before the panel dims


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

    def ambient_settings(self):
        return dict({'enabled': False, 'after': 120}, **self.config.get('ambient', {}))

    def leave_ambient(self):
        if self.ambient_active and self.panel is not None:
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
            if self.locked or now - self.last_activity < settings['after']:
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
        if (not settings['dim_after'] or self.dimmed or self.panel is None
                or now - self.last_activity < settings['dim_after']):
            return
        self.dim_display(f'after {settings["dim_after"]} s without a press')
