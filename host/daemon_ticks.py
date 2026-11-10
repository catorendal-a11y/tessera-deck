"""What the host does on its own every second: triggers, timers, plugins, sensors and reloading the configuration."""
import os
from pathlib import Path
import struct
import time

import psutil

from win_input import IS_WINDOWS


class BackgroundMixin:
    """Methods of the Daemon; they use its state."""

    def fire_trigger(self, when):
        for trigger in self.config.get('triggers', []):
            if trigger['when'] == when:
                self.enqueue(('actions', trigger.get('actions', [])))

    def trigger_tick(self, now):
        for index, trigger in enumerate(self.config.get('triggers', [])):
            spec, fire = trigger['when'], False
            before = self.trigger_state.get(index)
            kind = spec['type']
            value = before
            if kind == 'interval':
                if before is None:
                    value = now
                elif now-before >= spec['seconds']:
                    value, fire = now, True
            elif kind == 'daily':
                today = time.strftime('%Y-%m-%d')
                if time.strftime('%H:%M') >= spec['at'] and before != today:
                    value, fire = today, True
            elif kind == 'file':
                try:
                    value = os.stat(spec['path']).st_mtime_ns
                except (OSError, ValueError):
                    continue
                fire = before is not None and before != value
            elif kind == 'variable':
                value = self.custom_vars.get(spec['name'])
                fire = value is not None and before != value
            self.trigger_state[index] = value
            if fire:
                # Each trigger fires once; triggers of the same type are independent.
                self.enqueue(('actions', trigger.get('actions', [])))

    def agent_tick(self, now):
        if now < self.agent_scan_at:
            return
        self.agent_scan_at = now + 2
        names = set()
        try:
            for process in psutil.process_iter(['name']):
                name = process.info.get('name')
                if name:
                    names.add(name.lower())
        except (psutil.Error, OSError):
            return
        self.agents = {'codex': 'codex.exe' in names,
                       'claude': 'claude.exe' in names,
                       'zcode': 'zcode.exe' in names}

    def live_tick(self):
        """Announce timers that ran out: a notice for the tray, an optional sound and the timer's own actions."""
        for done in self.live.tick():
            self.log(f'Timer {done["name"]} finished')
            self.notices.append({'id': int(time.time() * 1000), 'title': 'Tessera timer', 'message': done['message']})
            if done['sound'] and IS_WINDOWS:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            if done['actions']:
                self.enqueue(('actions', done['actions']))
            self.enqueue(('push',))
        self.live.flush()

    def plugin_tick(self, now):
        # Starts, restarts and stops plugins to match the configuration (cheap; at most every 3 seconds).
        if self.plugins is None or now - self.plugins_checked < 3:
            return
        self.plugins_checked = now
        self.plugins.sync(self.config.get('plugins'))

    def stats_tick(self, now):
        if now < self.stats_scan_at:
            return
        self.stats_scan_at = now + 1
        try:
            self.stats.sample()
        except (OSError, ValueError, TypeError, struct.error) as exc:
            self.log(f'System sensors: {exc}')

    def reload_profiles(self):
        try:
            stamp = Path(self.args.profiles).stat().st_mtime_ns
        except OSError as exc:
            self.log(f'The configuration is temporarily unavailable; keeping the previous one: {exc}')
            return
        if stamp == self.profile_stamp:
            return
        self.profile_stamp = stamp
        try:
            config = self.load_profiles(self.args.profiles)
        except (ValueError, OSError) as exc:
            self.log(f'The configuration was rejected; keeping the previous one: {exc}')
            return
        with self.state_lock:
            # A trigger that did not change keeps its state, so saving the configuration does not
            # run today's daily triggers (or an unchanged variable trigger) a second time.
            before = self.config.get('triggers', [])
            kept = {index: self.trigger_state[index] for index, trigger in enumerate(config.get('triggers', []))
                    if index in self.trigger_state and index < len(before) and before[index].get('when') == trigger.get('when')}
            self.config = config
            if self.profile not in config['profiles']:
                self.profile = config.get('default_profile', next(iter(config['profiles'])))
            if self.page not in config['profiles'][self.profile]['pages']:
                self.page = next(iter(config['profiles'][self.profile]['pages']))
            self.trigger_state = kept
            self.folder_stack.clear()
            self.button_states.clear()
            self.enqueue(('force-push',))
            self.enqueue(('brightness',))
