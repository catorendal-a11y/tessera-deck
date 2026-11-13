#!/usr/bin/env python3
"""Tessera action engine and sole USB owner."""
import argparse
import collections
import itertools
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from ambient import Weather
import calendar_feed
from config_store import migrate
from plugins import EventLog, PluginManager
from live_state import LiveState
import widgets
from action_runner import Busy, CommandFailed, run_command
from control_api import ControlServer
import agent_activity
from datetime import datetime
import cockpit
import permission
from deck_assets import Assets
from program_locator import locate
from substitution import check_web_url, expand_environment, substitute
from pc_state import PcState, control_audio
from host_runtime import InstanceLock, SuspendableRLock, candidate_ports, remember_port, session_locked
from system_stats import SystemStats, gauge_state

# The engine's building blocks live in their own modules; the names stay importable from here for the editor,
# the tools and the tests.
from win_input import (CHILD_NAMES_SECONDS, IS_WINDOWS, VK, bring_to_front, child_names, dry_hotkey,  # noqa: F401
                       focus_existing_process, foreground_context, is_neutral_window,
                       matches_foreground, parse_hotkey, real_app_exe, send_hotkey, send_mouse, send_text)
from config_check import (ACTION_FIELDS, VARIABLE_NAME, _check_display, in_quiet_hours,  # noqa: F401
                          validate_config)
from daemon_display import DEFAULT_DIM_AFTER, DisplayMixin  # noqa: F401
from daemon_presses import (BLOCKING_ACTIONS, DOUBLE_PRESS_SECONDS, PressMixin,  # noqa: F401
                            action_list_name)
from daemon_ticks import BackgroundMixin
from panel_serial import (BOARD_ID, OFFLINE_LAYOUT_BYTES, SUPPORTED_PROTOCOLS, DeviceRejected,  # noqa: F401
                          PanelSerial, layout_bytes, layout_payload)

JOB_QUEUE_SIZE = 128
SLOW_LANE_LIMIT = 4
STALE_PRESS_SECONDS = 5  # a queued press older than this is dropped, never replayed
LOG_PATH = Path(__file__).resolve().parent / 'deck.local.log'
LOG_KEEP_BYTES = 5 * 1024 * 1024


def rotate_log():
    """The host runs for weeks: keep the log it writes to (its stdout) under 5 MB, the older part in .1."""
    try:
        fd = sys.stdout.fileno()
        opened = os.fstat(fd)
        if opened.st_size <= LOG_KEEP_BYTES or not os.path.samestat(opened, os.stat(LOG_PATH)):
            return
        sys.stdout.flush()
        shutil.copyfile(LOG_PATH, LOG_PATH.with_name('deck.local.log.1'))
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)  # stdout and stderr share this position: write from the start again
    except (OSError, ValueError, AttributeError):
        pass


PANEL_JOBS = ('press', 'api-press', 'feedback', 'push', 'force-push', 'brightness', 'dim', 'wake', 'panel-woke',
              'screen-deck')
CLOCK_INTERVAL = 600  # seconds between PC clock updates for panels without Wi-Fi


class ReconnectBackoff:
    """How long to wait before the next USB attempt, and whether this failure is worth a log line."""
    WAITS = (2, 5, 10)

    def __init__(self):
        self.failures, self.last_message = 0, None

    def failed(self, message):
        wait = self.WAITS[min(self.failures, len(self.WAITS) - 1)]
        # An unchanged problem is logged while the wait still grows, then stays quiet until it clears.
        log = message != self.last_message or self.failures < len(self.WAITS)
        self.failures, self.last_message = self.failures + 1, message
        return wait, log

    def recovered(self):
        failures, self.failures, self.last_message = self.failures, 0, None
        return failures





class Daemon(DisplayMixin, BackgroundMixin, PressMixin):
    def __init__(self, args, panel_factory=PanelSerial):
        self.args = args
        self.config = self.load_profiles(args.profiles)
        self.profile = self.config.get('default_profile', next(iter(self.config['profiles'])))
        self.page = next(iter(self.config['profiles'][self.profile]['pages']))
        self.auto_profile = None
        self.profile_locked = False
        self.panel_locked = False  # panel_lock: the panel ignores taps until a 2 s hold on its lock badge
        self.profile_before_auto = None  # restored when the program behind an auto switch loses focus
        self.view_before_auto = None  # (profile, page, folder stack) shown when the automatic switch happened
        self.resume_view = None  # that view, handed back to switch_profile once when the switch is undone
        # A profile chosen from a physical button stays selected while the same
        # foreground app remains active. Focus automation resumes on app change.
        self.manual_focus_exe = ''
        self.last_push = None
        # Labels of the last two acknowledged pushes of the shown page: a press
        # carries the label the panel showed, which a dynamic label may have
        # changed since. Another page's labels never match.
        self.pushed_labels = []
        self.last_action = None
        self.custom_vars = {}
        self.trigger_state = {}
        self.stop = threading.Event()
        self.jobs = queue.Queue(maxsize=JOB_QUEUE_SIZE)
        self.enqueue_lock = threading.Lock()
        self.state_lock = SuspendableRLock()
        self.input_lock = threading.Lock()  # keyboard and mouse sequences never interleave
        self.slow_slots = threading.BoundedSemaphore(SLOW_LANE_LIMIT)
        self.reconnect = ReconnectBackoff()
        self.sent_brightness = None  # the brightness last sent to the panel, to notice when quiet hours begin or end
        self.ambient_requested = False  # the clock was asked for by a screen action rather than by being idle
        self.pending_single = {}  # (profile, page, button) -> token of a first tap that may still become a double tap
        self.single_tokens = itertools.count(1)
        self.slow_running = set()
        self.slow_lock = threading.Lock()
        self.local = threading.local()
        self.dropped_jobs = 0
        self.device_info = {}
        self.weather = Weather()
        self.ambient_active = False
        self.ambient_sent = ''
        self.panel_factory = panel_factory
        self.panel = None
        self.connection_failed = threading.Event()
        self.folder_stack = []
        self.button_states = {}
        self.profile_stamp = Path(args.profiles).stat().st_mtime_ns
        self.runtime_path = Path(args.profiles).with_name('deck-runtime.local.json')
        self.runtime_written = 0.0
        self.foreground = {'exe': '', 'title': '', 'processes': []}
        self.agents = {'codex': False, 'claude': False, 'zcode': False}
        self.agent_scan_at = 0.0
        self.stats = SystemStats()
        self.pc = PcState()
        self.calendar = calendar_feed.Feed()
        self.events = EventLog()
        self.plugins = None
        self.plugins_checked = 0.0
        self.live = LiveState(Path(args.profiles).with_name('state.local.json'))
        self.cockpit_sent, self.cockpit_at = {}, 0.0
        self.panel_view, self.mixer_at = None, 0.0  # the panel's screen (2 = mixer), when the panel says
        # show_question (worker) and cockpit_tick (main loop) both send AD_AGENTS: one at a time, built from the
        # question open right then, so a closed question never comes back and a new one never vanishes
        self.agents_line_lock = threading.Lock()
        self.cockpit_mixer = []
        self.rail_items = []
        self.activity = agent_activity.AgentActivity()
        self.agent_seen, self.agent_started = {}, {}  # what each agent was doing a second ago, and since when
        self.agent_idle_since = {}  # agent -> (when it went idle, seconds that idle must last to count as finished)
        self.permissions = permission.Desk(lambda: self.enqueue(('question',)))
        self.notices = collections.deque(maxlen=5)
        self.stats_scan_at = 0.0
        self.assets = Assets(args.profiles)
        self.port = args.port
        self.dimmed = False
        self.locked = False
        self.last_activity = time.monotonic()
        self.clock_sent_at = float('-inf')
        self.device_state_path = Path(args.profiles).with_name('deck-device.local.json')

    @staticmethod
    def load_profiles(path):
        path = Path(path)
        if not path.exists():
            seed = path.with_name('profiles.default.json')
            if seed.exists():
                path.write_bytes(seed.read_bytes())
        with open(path, encoding='utf-8') as stream:
            return validate_config(migrate(json.load(stream)))

    @property
    def active_press(self):
        """The chain of buttons this thread is pressing (nested 'press' actions), for loop detection."""
        if not hasattr(self.local, 'active_press'):
            self.local.active_press = []
        return self.local.active_press

    @property
    def state_set_by_action(self):
        """Toggle keys this thread's press set with a 'state' action. Per thread, so a slow key's own set
        survives the worker running other presses while the slow key waits on a shell or delay."""
        if not hasattr(self.local, 'state_set_by_action'):
            self.local.state_set_by_action = set()
        return self.local.state_set_by_action

    def log(self, message):
        print(f'[{time.strftime("%H:%M:%S")}] {message}', flush=True)
        self.logged = getattr(self, 'logged', 0) + 1
        if self.logged % 200 == 0:
            rotate_log()

    def publish_runtime(self, connected, error=None, force=False):
        now = time.time()
        if not force and now - self.runtime_written < 1.5:
            return
        buttons = self.current_buttons()
        gauges = {str(item['id']): dict(item['gauge'], color=item['color']) for item in buttons if 'gauge' in item}
        state = {'pid': os.getpid(), 'updated': now, 'connected': bool(connected),
                 'port': self.port, 'profile': self.profile, 'page': self.page, 'gauges': gauges,
                 'dimmed': self.dimmed,
                 'buttons': len(buttons), 'layout_bytes': layout_bytes(buttons), 'error': str(error)[:180] if error else None,
                 'foreground': self.foreground.get('exe', ''), 'auto_profile': self.auto_profile,
                 'firmware': self.device_info.get('firmwareVersion'), 'protocol': self.device_info.get('protocol'),
                 'agents': self.agents, 'agent_states': dict(self.agent_seen), 'mixer': self.cockpit_mixer, 'stats': self.stats.display, 'sensor_hint': self.stats.hint, 'vars': self.custom_vars,
                 'notices': list(self.notices), 'variables': self.variables(),
                 'plugins': self.plugins.status(self.config.get('plugins')) if self.plugins else [],
                 'last_action': self.last_action}
        body = json.dumps(dict(state, updated=0), ensure_ascii=False)
        # Nothing changed: write it anyway before readers call it stale (5 s), not every 1.5 s.
        if not force and body == getattr(self, 'runtime_body', None) and now - self.runtime_written < 3:
            return
        temporary = self.runtime_path.with_suffix('.tmp')
        try:
            temporary.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, self.runtime_path)
            self.runtime_written, self.runtime_body = now, body
        except OSError:
            pass

    def variables(self):
        return dict(time=time.strftime('%H:%M'), date=time.strftime('%d.%m'),
                    profile=self.profile, page=self.page, profile_lock='LOCKED' if self.profile_locked else 'AUTO',
                    **{f'agent:{name}': 'ON' if running else 'OFF'
                       for name, running in self.agents.items()},
                    **{f'stat:{name}': value for name, value in self.stats.display.items()},
                    **self.pc.variables(),
                    **self.live.variables(),
                    **{f'var:{k}': str(v) for k, v in self.custom_vars.items()})

    def substitute(self, text, mode=None):
        return substitute(text, self.variables(), mode)

    @staticmethod
    def expand_environment(text):
        return expand_environment(text)

    def effective_buttons(self):
        item = self.config['profiles'][self.profile]
        values = {b['id']: b for b in item['pages'][self.page]}
        values.update({b['id']: b for b in item.get('pinned', [])})
        return list(values.values())

    def state_key(self, button):
        pinned = button in self.config['profiles'][self.profile].get('pinned', [])
        return (self.profile, '*' if pinned else self.page, button['id'])

    def resolved_button(self, button):
        states = button.get('states', [])
        index = self.button_states.get(self.state_key(button), 0)
        if states and button.get('bind'):
            bound = button['bind']  # follows the PC or a timer, not the presses
            index = int(self.live.is_running(bound[14:]) if bound.startswith('timer-running:') else self.pc.flag(bound))
        return dict(button, **states[index % len(states)]) if states else button

    def set_button_state(self, button_id, value):
        """Set a toggle button's state ('next' or a 0-based index) and refresh the panel."""
        button = next((b for b in self.effective_buttons() if b['id'] == button_id), None)
        if button is None:
            raise ValueError(f'Button {button_id} does not exist on this page')
        states = button.get('states', [])
        if not states:
            raise ValueError(f'Button {button_id} has no states')
        key = self.state_key(button)
        index = (self.button_states.get(key, 0) + 1) % len(states) if value == 'next' else value
        if not 0 <= index < len(states):
            raise ValueError(f'Button {button_id} has no state {index + 1}')
        self.button_states[key] = index
        self.state_set_by_action.add(key)
        self.push_page()

    def resolve_icon(self, button):
        """Icon the panel can show; 'app' and missing images come from the open action."""
        return self.assets.icon_for(button)

    def live_content(self, live):
        """What a wide key shows: the music that plays (title, artist, how far it is) or a timer (time left, ring)."""
        if live == 'media':
            media = self.pc.snapshot()
            result = {'label': (media['title'] or 'No music')[:24], 'sub': (media['artist'] or media['status'].capitalize())[:40]}
            if media.get('duration', 0) > 0:
                result['progress'] = max(0, min(100, round(media['position'] / media['duration'] * 100)))
            return result
        if isinstance(live, str) and live.startswith('timer:'):
            name = live[6:]
            timer = self.live.timers.get(name)
            left = self.live.remaining(name)
            result = {'label': self.live.variables().get(f'timer:{name}', '--:--'), 'sub': name[:40], 'ring': True}
            if timer and left is not None and timer['duration']:
                result['progress'] = max(0, min(100, round(left / timer['duration'] * 100)))
                result['sub'] = f'{name} · {timer["state"]}'[:40]
            return result
        if live == 'calendar':
            now = datetime.now()
            events, error = self.calendar.events(self.config.get('calendar'), now)
            return calendar_feed.content(events, now, error)
        if live in widgets.WIDGETS:
            return widgets.content(live, datetime.now(), self.stats.raw, self.pc.snapshot(),
                                   {name: self.agent_seen.get(key, '') for key, name, _ in cockpit.AGENTS})
        return {}

    def current_buttons(self):
        result = []
        for button in map(self.resolved_button, self.effective_buttons()):
            label = ''.join(c if ord(c) >= 32 else ' '
                            for c in self.substitute(button['label']))
            # The panel rejects a layout with an empty label, so a label that is
            # only an unset $(var:…) must not block the whole page.
            label = label or ' '
            color = button.get('color', '#35D07F')
            spec = button.get('stat')
            if isinstance(spec, dict):
                value = self.stats.raw.get(spec.get('key'))
                if value is not None and value >= spec.get('critical', float('inf')):
                    color = '#FF5252'
                elif value is not None and value >= spec.get('warn', float('inf')):
                    color = '#FFB74D'
            status = button.get('status')
            if isinstance(status, dict):
                color = status.get('colors', {}).get(str(self.custom_vars.get(status['var'], '')), color)
            if self.profile_locked and any(action.get('type') == 'profile_lock' for key in ('actions', 'hold_actions', 'double_actions')
                                           for action in button.get(key, [])):
                color = '#FFB13B'
            entry = dict(
                id=button['id'], label=label.encode('utf-8')[:24].decode('utf-8', 'ignore'),
                icon=self.resolve_icon(button), color=color, title=button.get('title', {}))
            if button.get('hold_actions'):
                entry['hold'] = True  # the panel reports long presses for this key
            if button.get('double_actions'):
                entry['double'] = True  # the panel draws a mark; the host tells one tap from two
            if button.get('confirm') is True:
                entry['cf'] = 1  # the panel sends the press only after a 600 ms hold
            if button.get('span', 1) > 1:
                entry['span'] = button['span']
                entry.update(self.live_content(button.get('live')))
                # the panel keeps 24 bytes and reports the label it shows with a press; a longer one would not match
                entry['label'] = entry['label'].encode('utf-8')[:24].decode('utf-8', 'ignore')
            entry.update(self.config.get('theme', {}))  # the theme is the default look; a key's own colors win
            entry.update({key: button[key] for key in ('bg', 'text_color', 'border') if key in button})
            if isinstance(button.get('gauge'), dict):
                state = gauge_state(button['gauge'], dict(self.stats.raw, **self.live.raw()), color)
                entry.update(color=state['color'], gauge={'p': state['p'], 't': state['t'], **({'b': button['gauge']['badge']} if 'badge' in button['gauge'] else {})})
            result.append(entry)
        return result

    def push_page(self, force=False):
        if self.panel is None or self.connection_failed.is_set():
            self.last_push = None  # nothing to draw on; the page is pushed in full when a panel connects
            return
        buttons = self.current_buttons()
        payload = json.dumps(buttons, sort_keys=True)
        if force or payload != self.last_push:
            if hasattr(self.panel, 'push_assets'):
                self.panel.push_assets(buttons, self.assets)
            if not self.dimmed:
                self.panel.send_line('AD_DISPLAY_WAKE')
            self.panel.push_buttons(buttons)
            self.panel.send_line('AD_CONTEXT ' + json.dumps({'profile': self.profile, 'page': self.page,
                                                             'canBack': bool(self.folder_stack)}))
            self.last_push = payload
            path = (self.profile, self.page)
            labels = {b['id']: b['label'] for b in buttons}
            fresh = force or not self.pushed_labels or self.pushed_labels[-1][0] != path
            self.pushed_labels = [entry for entry in self.pushed_labels if entry[0] == path][-1:] + [(path, labels)]
            if fresh:  # live values refresh the page every few seconds; that is not news for the log
                self.log(f'{self.profile} / {self.page}: {len(buttons)} buttons acknowledged')

    def switch_page(self, page, folder=False):
        if not getattr(self, 'rail_moving', False):
            self.before_shortcut = None  # you moved on your own: Keys no longer goes back to before a shortcut
        if page not in self.config['profiles'][self.profile]['pages']:
            raise ValueError(f'Unknown page: {page}')
        if folder:
            if len(self.folder_stack) >= 16:
                raise ValueError('Folders are nested more than 16 levels deep')
            self.folder_stack.append(self.page)
        else:
            self.folder_stack.clear()
        self.page = page
        self.events.add('page', profile=self.profile, page=page)
        self.push_page(force=True)
        return True

    def switch_profile(self, profile, auto=False):
        if not getattr(self, 'rail_moving', False):
            self.before_shortcut = None
        if profile not in self.config['profiles']:
            raise ValueError(f'Unknown profile: {profile}')
        resume, self.resume_view = self.resume_view, None
        if profile != self.profile:
            self.folder_stack.clear()
            self.profile = profile
            pages = self.config['profiles'][profile]['pages']
            self.page = next(iter(pages))
            if auto and resume and resume[0] == profile and resume[1] in pages:
                self.page = resume[1]
                self.folder_stack.extend(name for name in resume[2] if name in pages)
            self.events.add('profile', profile=profile, page=self.page)
            self.push_page(force=True)  # an identical-looking page must still send the new profile name and path
        if not auto:
            self.auto_profile = None
            self.manual_focus_exe = self.foreground.get('exe', '')
        return True

    def go_home(self):
        profile = self.config.get('default_profile', next(iter(self.config['profiles'])))
        self.switch_profile(profile)
        first_page = next(iter(self.config['profiles'][profile]['pages']))
        if self.page != first_page:
            self.switch_page(first_page)
        else:
            self.push_page(force=True)
        return True

    def run_action(self, action):
        kind = action['type']
        if kind == 'hotkey':
            with self.input_turn():
                send_hotkey(action['keys'])
        elif kind == 'text':
            text, pause = self.substitute(action['text']), action.get('delay_ms', 0) / 1000
            if pause:  # typing slowly can take minutes: let other keys, the API and the main loop run meanwhile
                with self.state_lock.suspended(), self.input_lock:
                    send_text(text, pause, self.stop.wait)  # a stopping host ends the typing
            else:
                with self.input_turn():
                    send_text(text)
        elif kind == 'open':
            target = self.substitute(action['target'])
            if IS_WINDOWS:
                process = action.get('process', '')
                if not (action.get('reuse', False) and focus_existing_process(process)):
                    expanded = os.path.expandvars(target)
                    os.startfile(expanded if os.path.exists(expanded) else locate(expanded) or expanded)
            else:
                subprocess.Popen(['xdg-open', target])
        elif kind == 'shell':
            command, timeout = self.substitute(action['command'], 'shell'), action.get('timeout', 30)
            with self.state_lock.suspended():  # the panel and API stay responsive while it runs
                try:
                    run_command(command, timeout, self.stop)
                except CommandFailed as exc:
                    raise RuntimeError(str(exc)) from exc
        elif kind == 'http':
            # $(env:NAME) is expanded before the variables, so a variable's value can never pull in a secret
            headers = {name: self.substitute(self.expand_environment(value))
                       for name, value in action.get('headers', {}).items()}
            request = urllib.request.Request(check_web_url(self.expand_environment(self.substitute(action['url'], 'url'))),
                method=action.get('method', 'GET'), headers=headers,
                data=self.substitute(self.expand_environment(action.get('body', ''))).encode() or None)
            with self.state_lock.suspended():
                with urllib.request.urlopen(request, timeout=action.get('timeout', 5)) as response:
                    response.read(65536)
        elif kind == 'delay':
            with self.state_lock.suspended():
                self.stop.wait(action.get('ms', 100)/1000)
        elif kind == 'page':
            self.switch_page(action['page'])
        elif kind == 'folder':
            self.switch_page(action['page'], folder=True)
        elif kind == 'back':
            if self.folder_stack:
                self.page = self.folder_stack.pop()
                self.push_page(force=True)
        elif kind == 'home':
            self.go_home()
        elif kind == 'profile':
            self.switch_profile(action['profile'])
        elif kind == 'profile_lock':
            self.profile_locked = not self.profile_locked
            self.manual_focus_exe = ''
            self.push_page(force=True)
        elif kind == 'panel_lock':
            mode = action.get('mode', 'toggle')
            self.panel_locked = (not self.panel_locked) if mode == 'toggle' else mode == 'on'
            if self.panel is not None:
                self.panel.send_line(f'AD_PANEL_LOCK {int(self.panel_locked)}')
        elif kind == 'press':
            if not self.dispatch_press(int(action['id'])):
                raise ValueError('The child button failed')
        elif kind == 'state':
            self.set_button_state(action['button'], action.get('state', 'next'))
        elif kind == 'mouse':
            with self.input_turn():
                send_mouse(action['op'], action.get('x', 0), action.get('y', 0), action.get('amount', 0))
        elif kind == 'plugin':
            self.events.add('command', plugin=action['plugin'], command=action['command'], args=action.get('args', {}))
        elif kind == 'counter':
            self.live.apply_counter(action)
            self.push_page()
        elif kind == 'timer':
            self.live.apply_timer(action)
            self.push_page()
        elif kind == 'screen':
            self.show_screen(action['show'])
        elif kind == 'audio':
            control_audio(action['target'], action.get('op', 'toggle'), action.get('value'), action.get('step', 5))
            self.pc.poll()
            self.push_page()
        elif kind == 'set':
            self.custom_vars[action['variable']] = self.substitute(str(action.get('value', '')))
            self.push_page()
        else:
            raise ValueError(f'Unknown action: {kind}')
        return True

    def heartbeat(self, panel, now):
        """One beat: keeps the panel's PC indicator lit and its clock right without Wi-Fi."""
        panel.send_line('AD_PING')
        if now - self.clock_sent_at >= CLOCK_INTERVAL:
            panel.send_line('AD_TIME ' + time.strftime('%Y-%m-%dT%H:%M:%S'))
            self.clock_sent_at = now

    def heartbeat_loop(self, panel):
        # A thread of its own: slow sensor or focus ticks must not make the
        # panel report a lost PC.
        try:
            while not self.stop.is_set() and panel is self.panel and not self.connection_failed.is_set():
                self.heartbeat(panel, time.monotonic())
                self.stop.wait(1)
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            if panel is self.panel and not self.stop.is_set():  # without a heartbeat the panel shows a lost PC
                self.log(f'Heartbeat failed: {exc!r}')
                self.connection_failed.set()

    def submit(self, *jobs):
        """Queue jobs all-or-nothing; raises Busy when the queue cannot take them, so callers can report it."""
        with self.enqueue_lock:
            if self.jobs.maxsize - self.jobs.qsize() < len(jobs):
                self.dropped_jobs += len(jobs)
                raise Busy('The host is busy: the action queue is full')
            for job in jobs:
                self.jobs.put_nowait(job)

    def schedule_job(self, job, delay):
        timer = threading.Timer(delay, self.enqueue_later, args=(job,))
        timer.daemon = True
        timer.start()

    def enqueue_later(self, job):
        """A timer's job. A dropped 'single-due' forgets its waiting tap, or a tap minutes later would count as
        the second of a double tap. The single tap itself is dropped, like any press a full queue cannot take."""
        if not self.enqueue(job) and job[0] == 'single-due':
            _, identity, token = job
            with self.state_lock:
                if (self.pending_single.get(identity) or (None,))[0] == token:
                    del self.pending_single[identity]

    def enqueue(self, job):
        """Queue a job from inside the host; a full queue is logged and counted. Returns whether it was queued."""
        try:
            self.submit(job)
        except Busy as exc:
            self.log(f'{exc}; dropped {job[0]}')
            return False
        return True

    def drop_queued_presses(self):
        """Forget key presses queued before a reconnect so they are never replayed against the new session."""
        kept, dropped = [], 0
        with self.enqueue_lock:
            while True:
                try:
                    job = self.jobs.get_nowait()
                except queue.Empty:
                    break
                self.jobs.task_done()
                if job[0] in ('press', 'api-press'):
                    dropped += 1
                else:
                    kept.append(job)
            for job in kept:
                self.jobs.put_nowait(job)
        if dropped:
            self.log(f'Dropped {dropped} queued key press(es) from before the reconnect')

    def reader_loop(self, panel):
        try:
            while not self.stop.is_set() and panel is self.panel:
                for line in panel.read_lines():
                    if line.startswith('AD_CFG_END '):
                        panel.cfg_reply = line
                        panel.cfg_done.set()
                    if line.startswith('AD_IMG_END '):
                        panel.asset_reply = line
                        panel.asset_done.set()
                    if line.startswith('{'):
                        try:
                            message = json.loads(line)
                        except ValueError:
                            continue
                        if not isinstance(message, dict):
                            continue
                        if message.get('type') == 'deck_event':
                            if type(message.get('button')) is int:
                                self.enqueue(('press', message['button'], message.get('label'),
                                              message.get('hold') is True, time.monotonic()))
                        elif message.get('type') == 'wake':
                            self.enqueue(('panel-woke',))
                        elif message.get('type') == 'unlocked':
                            self.enqueue(('panel-unlocked',))
                        elif message.get('type') == 'brightness' and type(message.get('level')) is int and 1 <= message['level'] <= 100:
                            self.enqueue(('panel-brightness', message['level']))
                        elif message.get('type') == 'screen' and message.get('by') == 'touch':
                            self.enqueue(('screen-deck',))
                        elif message.get('type') == 'fader' and isinstance(message.get('id'), str) and type(message.get('level')) is int:
                            self.enqueue(('fader', message['id'][:80], max(0, min(100, message['level']))))
                        elif message.get('type') == 'image' and isinstance(message.get('id'), str) and message['id'].startswith('im:'):
                            self.enqueue(('image-missing', message['id'][:80]))
                        elif message.get('type') == 'view':
                            view = message.get('v')
                            self.panel_view = view if type(view) is int else None
                            if view != 0:  # a tap on Keys was never counted, so the clock still comes over the keys
                                self.last_activity = time.monotonic()
                            if view == 2:
                                self.mixer_at = 0.0  # the mixer screen opened: read the sound devices now
                        elif message.get('type') == 'rail' and type(message.get('i')) is int:
                            self.enqueue(('rail', message['i']))
                        elif message.get('type') == 'mute' and isinstance(message.get('id'), str):
                            self.enqueue(('mute', message['id'][:80]))
                        elif message.get('type') == 'agent' and message.get('do') in cockpit.AGENT_ACTIONS and cockpit.agent_exe(message.get('id')):
                            self.enqueue(('agent', message['id'], message['do']))
                    elif self.args.verbose and line:
                        self.log('Panel: ' + line[:200])
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            if not self.stop.is_set():
                self.log(f'USB disconnected: {exc}')
                self.publish_runtime(False, exc, force=True)
        finally:
            if panel is self.panel:
                self.connection_failed.set()

    def handle_job(self, job):
        kind = job[0]
        if kind == 'press':
            if self.dimmed:
                self.wake_display()  # the press that wakes the panel is not an action
                return
            if len(job) > 4 and time.monotonic() - job[4] > STALE_PRESS_SECONDS:
                self.dropped_jobs += 1
                self.log(f'Dropped a stale key press for button {job[1]}')
                self.give_feedback(job[1], False)
                return
            self.last_activity = time.monotonic()
            current = next((b for b in self.current_buttons() if b['id'] == job[1]), None)
            path = (self.profile, self.page)
            shown = job[2] is None or job[2] == (current or {}).get('label') or any(
                entry_path == path and labels.get(job[1]) == job[2] for entry_path, labels in self.pushed_labels)
            if current and shown:
                hold = len(job) > 3 and job[3]
                if not hold and any(b['id'] == job[1] and b.get('double_actions') for b in self.effective_buttons()):
                    self.tap_with_double(job[1], job[4] if len(job) > 4 else None)
                else:
                    self.start_press(job[1], hold=hold)
            else:  # the panel showed another key there (a page change crossed the press)
                self.log(f'Ignored a press on button {job[1]}: the panel showed a different key')
                self.give_feedback(job[1], False)
        elif kind == 'single-due':
            _, identity, token = job
            if (self.pending_single.get(identity) or (None,))[0] == token:
                del self.pending_single[identity]
                if identity[:2] == (self.profile, self.page):
                    self.start_press(identity[2])
        elif kind == 'profile':
            self.switch_profile(job[1], auto=True)
        elif kind == 'focus-profile':
            if not self.profile_locked:
                self.switch_profile(job[1], auto=True)
        elif kind == 'page':
            self.switch_page(job[1])
        elif kind == 'actions':
            self.start_actions(job[1])
        elif kind == 'push':
            # Live values are not refreshed under a dark screen or the clock: the next push after waking sends them.
            if not (getattr(self, 'dimmed', False) or getattr(self, 'ambient_active', False)):
                self.push_page()
        elif kind == 'force-push':
            self.push_page(force=True)
        elif kind == 'brightness':
            self.apply_brightness()
        elif kind == 'var':
            self.custom_vars[job[1]] = str(job[2])
            self.push_page()
        elif kind == 'state':
            self.set_button_state(job[1], job[2])
        elif kind == 'feedback':
            self.panel.feedback(job[1], job[2])
        elif kind == 'api-press':
            self.wake_display()
            self.start_press(job[1])
        elif kind == 'dim':
            self.dim_display('by request')
        elif kind == 'wake':
            self.wake_display()
        elif kind == 'screen-deck':
            # A touch on the ambient screen already returned the panel to the deck.
            self.last_activity = time.monotonic()
            self.ambient_active = self.ambient_requested = False
        elif kind == 'question':
            self.show_question()
        elif kind == 'image-missing':
            # the panel dropped an image from its cache that the host thought it had: send it again, at most
            # once a minute per image, so an image that cannot be shown does not loop
            asked = getattr(self, 'images_asked', {})
            self.images_asked = asked
            if self.panel is not None and time.monotonic() - asked.get(job[1], -1e9) > 60:
                asked[job[1]] = time.monotonic()
                self.panel.assets_sent.pop(job[1], None)
                self.push_page(force=True)
        elif kind == 'rail':
            self.last_activity = time.monotonic()
            if self.dimmed:  # the first touch on a dimmed panel only wakes it, like a key
                self.wake_display()
            else:
                self.use_rail_shortcut(job[1])
        elif kind in ('fader', 'mute', 'agent'):
            self.last_activity = time.monotonic()
            if kind == 'fader':
                control_audio(job[1], 'volume', job[2])
            elif kind == 'mute':
                control_audio(job[1], 'toggle')
                self.cockpit_at = 0.0  # show the new state on the panel at once
            else:
                self.agent_action(job[1], job[2])
        elif kind == 'panel-unlocked':
            self.panel_locked = False  # unlocked on the panel by a hold on its lock badge
            self.log('Panel unlocked by touch')
        elif kind == 'panel-brightness':
            self.save_panel_brightness(job[1])
        elif kind == 'panel-woke':
            # The panel already restored its backlight after a touch.
            self.last_activity = time.monotonic()
            self.leave_ambient()
            if self.dimmed:
                self.log('Panel woke by touch')
            self.dimmed = False

    def worker_loop(self):
        while not self.stop.is_set():
            try:
                job = self.jobs.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                with self.state_lock:
                    offline = self.connection_failed.is_set() or self.panel is None
                    if offline and job[0] in PANEL_JOBS:
                        self.dropped_jobs += 1
                        self.log(f'The panel is not connected; dropped {job[0]}')
                    else:
                        self.handle_job(job)
            except Exception as exc:
                self.log(f'Action failed: {exc}')
            finally:
                self.jobs.task_done()

    def focus_tick(self):
        if self.profile_locked or self.args.no_focus or not self.config.get('auto_profiles', True):
            return
        context = foreground_context()
        self.foreground = context
        if not context.get('exe') or is_neutral_window(context):
            return
        if self.manual_focus_exe:
            if context['exe'] == self.manual_focus_exe:
                return
            self.manual_focus_exe = ''
        match = next((name for name, p in self.config['profiles'].items()
                      if any(matches_foreground(pattern, context) for pattern in p.get('match', []))), None)
        if match:
            if match != self.profile:
                if self.auto_profile is None:
                    self.profile_before_auto = self.profile
                    self.view_before_auto = (self.profile, self.page, list(self.folder_stack))
                self.auto_profile = match
                self.enqueue(('focus-profile', match))
        elif self.auto_profile is not None:
            self.auto_profile = None
            before, self.profile_before_auto = self.profile_before_auto, None
            self.resume_view, self.view_before_auto = self.view_before_auto, None
            fallback = self.config.get('default_profile', next(iter(self.config['profiles'])))
            self.enqueue(('focus-profile', before if before in self.config['profiles'] else fallback))

    def open_panel(self):
        """Open the first candidate port that completes the identity and protocol handshake."""
        failures = []
        for port in candidate_ports(self.args.port, self.device_state_path):
            try:
                return self.panel_factory(port, self.log), port
            except DeviceRejected as exc:
                failures.append(str(exc))
            except OSError as exc:
                failures.append(f'{port}: {exc}')
        raise OSError('; '.join(failures) or 'No USB port found')

    def run(self):
        threading.Thread(target=self.worker_loop, daemon=True).start()
        self.api = ControlServer(self, Path(self.args.profiles).with_name('deck-api.local.json'))
        self.api.start()
        self.plugins = PluginManager(Path(__file__).resolve().parents[1] / 'plugins', Path(__file__).with_name('plugins'),
                                     lambda: f'http://127.0.0.1:{self.api.server.server_port}', self.api.add_grant,
                                     self.api.remove_grant, log=self.log)
        self.pc.start()
        # Standalone Deck host: the USB owner only handles buttons and assets.
        startup_fired = False
        retry_at, connect_error = 0.0, None  # triggers, timers and plugins keep running while no panel is connected
        try:
            while not self.stop.is_set():
                stop_path = Path(__file__).with_name('deck-stop.local.json')
                if stop_path.exists():
                    try:
                        if json.loads(stop_path.read_text(encoding='utf-8')).get('pid') == os.getpid():
                            self.stop.set()
                            continue
                    except (ValueError, OSError, AttributeError):
                        pass
                if (self.panel is None or self.connection_failed.is_set()) and time.monotonic() >= retry_at:
                    if self.panel:
                        self.panel.close()
                    self.panel = None
                    try:
                        self.panel, self.port = self.open_panel()
                        self.device_info = getattr(self.panel, 'info', {}) or {}
                        self.cockpit_sent = {}
                        if self.question_open():
                            self.enqueue(('question',))
                        remember_port(self.port, self.device_state_path)
                        self.connection_failed.clear()
                        connect_error = None
                        threading.Thread(target=self.reader_loop, args=(self.panel,), daemon=True).start()
                        self.clock_sent_at = float('-inf')
                        threading.Thread(target=self.heartbeat_loop, args=(self.panel,), daemon=True).start()
                        self.drop_queued_presses()
                        self.ambient_active, self.ambient_requested, self.ambient_sent = False, False, ''
                        with self.state_lock:
                            self.last_activity = time.monotonic()
                            self.apply_brightness()
                            if self.panel_locked:  # a restarted panel boots unlocked
                                self.panel.send_line('AD_PANEL_LOCK 1')
                            self.push_page(force=True)
                            if (self.device_info.get('protocol') or 1) >= 3:
                                self.panel.send_line('AD_SCREEN deck')  # a restarted host may find the ambient clock showing
                        self.publish_runtime(True, force=True)
                        missed = self.reconnect.recovered()
                        self.log(f'USB ready on {self.port}' + (f' after {missed} failed attempts' if missed > 1 else ''))
                        if not startup_fired:
                            self.fire_trigger({'type': 'startup'})
                            startup_fired = True
                    except (OSError, ValueError, TimeoutError) as exc:
                        wait, show = self.reconnect.failed(str(exc))
                        if show:
                            self.log(f'USB: {exc}; retrying in {wait} seconds')
                        self.publish_runtime(False, exc, force=True)
                        self.connection_failed.set()
                        retry_at, connect_error = time.monotonic() + wait, exc
                now = time.monotonic()
                for tick, arguments in ((self.agent_tick, (now,)), (self.stats_tick, (now,)), (self.ambient_tick, (now,)),
                                        (self.plugin_tick, (now,)), (self.cockpit_tick, (now,)), (self.agent_notice_tick, (now,)), (self.live_tick, ()), (self.brightness_tick, ()), (self.focus_tick, ()),
                                        (self.reload_profiles, ())):
                    try:
                        tick(*arguments)
                    except Exception as exc:
                        self.log(f'Background task failed: {exc!r}')
                command_path = Path(__file__).with_name('deck-command.local.json')
                if command_path.exists():
                    try:
                        command = json.loads(command_path.read_text(encoding='utf-8'))
                        if command.get('profile') in self.config['profiles']:
                            self.enqueue(('wake',))
                            self.enqueue(('profile', command['profile']))
                            if command.get('page') in self.config['profiles'][command['profile']]['pages']:
                                self.enqueue(('page', command['page']))
                        command_path.unlink()
                    except (OSError, ValueError, AttributeError, TypeError, KeyError):
                        command_path.unlink(missing_ok=True)  # an unreadable command is dropped, not retried forever
                try:
                    with self.state_lock:
                        self.trigger_tick(time.monotonic())
                        self.lock_tick(session_locked())
                        self.idle_tick(time.monotonic())
                except Exception as exc:  # e.g. the cable was pulled while dimming: the reader loop reconnects
                    self.log(f'Background task failed: {exc!r}')
                online = self.panel is not None and not self.connection_failed.is_set()
                try:
                    self.publish_runtime(online, None if online else connect_error)
                except Exception as exc:  # a full disk or a locked file must not end the host
                    self.log(f'Background task failed: {exc!r}')
                if online:
                    self.enqueue(('push',))
                self.stop.wait(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop.set()
            if self.plugins is not None:
                self.plugins.stop_all()
            self.api.stop()
            self.pc.stop()
            self.live.flush()
            self.publish_runtime(False, 'The host has stopped', force=True)
            if self.panel:
                self.panel.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM4')
    parser.add_argument('--profiles', default=str(Path(__file__).with_name('profiles.json')))
    parser.add_argument('--no-focus', action='store_true')
    parser.add_argument('--selftest', '--validate', dest='validate', action='store_true',
                        help='Validate the configuration without USB or key presses')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    Daemon.load_profiles(args.profiles)
    if args.validate:
        print('Configuration and hotkeys are valid. No actions were run.')
        return
    lock = InstanceLock(Path(__file__).with_name('deck-host.local.lock'))
    if not lock.acquire():
        print('Another Tessera host is already running; exiting.')
        return
    try:
        Daemon(args).run()
    finally:
        lock.release()


if __name__ == '__main__':
    main()
