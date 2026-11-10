"""What the host does on its own every second: triggers, timers, plugins, sensors and reloading the configuration."""
import os
from pathlib import Path
import struct
import time

import psutil

import agent_activity
import cockpit
from win_input import IS_WINDOWS, focus_existing_process


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

    def uses_cockpit(self):
        return (self.device_info.get('protocol') or 1) >= cockpit.PROTOCOL

    def agent_action(self, agent_id, action):
        """A lane button on the agents screen.

        Allow and Deny answer the permission prompt the panel is showing (see permission.py). Without an open
        prompt a button brings the tool's window to the front. Plugins are told either way.
        """
        self.events.add('agent', agent=agent_id, action=action)
        if self.permissions.answer(agent_id, action):
            self.log(f'Agent {agent_id}: {action}, answered from the panel')
            return
        exe = cockpit.agent_exe(agent_id)
        shown = bool(exe) and focus_existing_process(exe)
        self.log(f'Agent {agent_id}: {action}' + ('' if shown else ' (its window was not found)'))

    def agent_view(self):
        """The variables the agents screen is drawn from: hooks first, the tools' own session files for the rest."""
        try:
            activity = self.activity.read()
        except OSError:
            activity = {}
        return agent_activity.merge(self.custom_vars, activity, self.agents)

    def agent_notice_tick(self, now):
        """A Windows notice (shown by the tray) the moment an agent starts waiting for you, or finishes long work."""
        view = self.agent_view()
        states = {key: str(view.get(key, '')) for key, _, _ in cockpit.AGENTS}
        names = {key: name for key, name, _ in cockpit.AGENTS}
        for key, state in states.items():
            before = self.agent_seen.get(key)
            if state == 'working' and before != 'working':
                self.agent_started[key] = now
            if before is not None and before != state:
                if state == 'waiting':
                    self.notify(names[key], str(view.get(f'{key}.message') or 'Waiting for you'))
                elif before == 'working' and state == 'idle' and now - self.agent_started.get(key, now) >= 60:
                    self.notify(names[key], 'Finished' + (f' in {view[f"{key}.project"]}' if view.get(f'{key}.project') else ''))
        self.agent_seen = states

    def notify(self, title, message):
        self.notices.append({'id': int(time.time() * 1000), 'title': title, 'message': message[:120]})

    def panel_takes_questions(self):
        return self.panel is not None and not self.connection_failed.is_set() and self.uses_cockpit()

    def ask_permission(self, agent, text):
        """Called by the control API: blocks until Allow or Deny is touched, or returns None."""
        return self.permissions.ask(agent, text, self.panel_takes_questions)

    def show_question(self):
        """A permission prompt opened or closed: wake the panel, bring up the agents screen and redraw the lanes."""
        if not self.panel_takes_questions():
            return
        asking = self.permissions.current()
        if asking:
            self.wake_display()
            self.panel.send_line('AD_VIEW agents')
        payload = cockpit.agents_payload(self.agent_view(), self.agents, asking, self.config.get('panel', {}).get('agents'))
        self.panel.send_line(f'AD_AGENTS {payload}')
        self.cockpit_sent['AD_AGENTS'] = payload

    def cockpit_tick(self, now):
        """Keep the agents, mixer and status screens of a cockpit panel current: once a second, only what changed."""
        if (self.panel is None or self.connection_failed.is_set() or not self.uses_cockpit()
                or now - self.cockpit_at < 1):
            return
        self.cockpit_at = now
        choice = self.config.get('panel', {})
        lines = {'AD_AGENTS': cockpit.agents_payload(self.agent_view(), self.agents, self.permissions.current(),
                                                     choice.get('agents')),
                 'AD_STATS': cockpit.stats_payload(self.stats.display, self.stats.raw, choice.get('stats') or None)}
        try:
            self.cockpit_mixer = cockpit.read_mixer(choice.get('apps'), choice.get('mic', True))
            lines['AD_MIXER'] = cockpit.mixer_payload(self.cockpit_mixer)
        except (OSError, ImportError):
            pass  # no sound device or no audio library: the mixer screen keeps what it had
        for command, payload in lines.items():
            if self.cockpit_sent.get(command) != payload:
                self.panel.send_line(f'{command} {payload}')
                self.cockpit_sent[command] = payload

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
