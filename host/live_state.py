"""Counters and countdown timers that survive restarts.

Counters are whole numbers changed by the `counter` action. Timers are countdowns started by the
`timer` action; a running timer stores its absolute end time, so it keeps counting while Tessera is
closed. Everything is saved to one small JSON file (atomically, only when something changed).
Values reach labels as $(counter:NAME), $(timer:NAME) and $(timer-state:NAME), and gauges as the raw
values `counter:NAME` and `timer:NAME` (seconds left).
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable

NAME = re.compile(r'[A-Za-z0-9_.-]{1,64}')
COUNTER_OPS = ('inc', 'dec', 'set', 'reset')
TIMER_OPS = ('start', 'pause', 'resume', 'stop', 'toggle')
MAX_COUNTERS = 200
MAX_TIMERS = 50
MAX_VALUE = 1_000_000_000
MAX_SECONDS = 7 * 24 * 3600
MAX_NOTE = 120
VERSION = 1


def _whole(value, low, high, message):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(message)


def check_counter(action: dict) -> None:
    if not isinstance(action.get('name'), str) or not NAME.fullmatch(action['name']):
        raise ValueError('counter: name must be 1-64 letters, digits, dots, dashes or underscores')
    if action.get('op', 'inc') not in COUNTER_OPS:
        raise ValueError(f'counter: op must be one of {", ".join(COUNTER_OPS)}')
    _whole(action.get('step', 1), 1, MAX_VALUE, 'counter: step must be a whole number above 0')
    for key in ('value', 'min', 'max'):
        if key in action:
            _whole(action[key], -MAX_VALUE, MAX_VALUE, f'counter: {key} must be a whole number')
    if 'min' in action and 'max' in action and action['min'] > action['max']:
        raise ValueError('counter: min is above max')
    if type(action.get('wrap', False)) is not bool:
        raise ValueError('counter: wrap must be true or false')


def check_timer(action: dict) -> None:
    if not isinstance(action.get('name'), str) or not NAME.fullmatch(action['name']):
        raise ValueError('timer: name must be 1-64 letters, digits, dots, dashes or underscores')
    if action.get('op', 'toggle') not in TIMER_OPS:
        raise ValueError(f'timer: op must be one of {", ".join(TIMER_OPS)}')
    if 'seconds' in action:
        _whole(action['seconds'], 1, MAX_SECONDS, 'timer: seconds must be 1 to 604800')
    if not isinstance(action.get('notify', ''), str) or len(action.get('notify', '')) > MAX_NOTE:
        raise ValueError(f'timer: notify must be text of at most {MAX_NOTE} characters')
    if type(action.get('sound', False)) is not bool:
        raise ValueError('timer: sound must be true or false')
    if not isinstance(action.get('actions', []), list):
        raise ValueError('timer: actions must be a list')


def clock_text(seconds: float) -> str:
    """MM:SS, or H:MM:SS from one hour; rounds up so a timer shows 00:01 until it really ends."""
    whole = max(0, math.ceil(seconds))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f'{hours}:{minutes:02d}:{secs:02d}' if hours else f'{minutes:02d}:{secs:02d}'


class LiveState:
    def __init__(self, path, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self._clock = clock
        self._lock = threading.RLock()
        self.counters: dict[str, int] = {}
        self.timers: dict[str, dict] = {}
        self._dirty = False
        self.load()

    # --- persistence ----------------------------------------------------------------
    def load(self) -> None:
        """Read the saved state; a missing or damaged file starts clean. Timers that ended while closed are done."""
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict) or data.get('version') != VERSION:
            return
        now = self._clock()
        counters, timers = data.get('counters'), data.get('timers')
        for name, value in (counters.items() if isinstance(counters, dict) else ()):
            if NAME.fullmatch(str(name)) and type(value) is int and abs(value) <= MAX_VALUE:
                self.counters[name] = value
        for name, saved in (timers.items() if isinstance(timers, dict) else ()):
            timer = self._clean_timer(name, saved)
            if timer is None:
                continue
            if timer['state'] == 'running' and now >= timer['ends_at']:
                timer.update(state='done', remaining=0.0)
            self.timers[name] = timer

    @staticmethod
    def _clean_timer(name, saved):
        try:
            if not NAME.fullmatch(str(name)) or saved['state'] not in ('idle', 'running', 'paused', 'done'):
                return None
            duration = int(saved['duration'])
            if not 1 <= duration <= MAX_SECONDS:
                return None
            actions = saved.get('actions', [])
            return {'state': saved['state'], 'duration': duration,
                    'remaining': min(float(saved.get('remaining', duration)), duration),
                    'ends_at': float(saved.get('ends_at', 0)), 'notify': str(saved.get('notify', ''))[:MAX_NOTE],
                    'sound': saved.get('sound') is True, 'actions': actions if isinstance(actions, list) else []}
        except (KeyError, TypeError, ValueError, AttributeError):
            return None

    def flush(self) -> None:
        """Write the state if it changed since the last write."""
        with self._lock:
            if not self._dirty:
                return
            payload = {'version': VERSION, 'counters': self.counters, 'timers': self.timers}
            temporary = self.path.with_suffix('.tmp')
            try:
                temporary.write_text(json.dumps(payload), encoding='utf-8')
                os.replace(temporary, self.path)
                self._dirty = False
            except OSError:
                pass  # try again on the next flush

    # --- counters --------------------------------------------------------------------
    def apply_counter(self, action: dict) -> int:
        check_counter(action)
        name, op = action['name'], action.get('op', 'inc')
        with self._lock:
            if name not in self.counters and len(self.counters) >= MAX_COUNTERS:
                raise ValueError('Too many counters')
            step = action.get('step', 1)
            if op == 'inc':
                value = self.counters.get(name, 0) + step
            elif op == 'dec':
                value = self.counters.get(name, 0) - step
            else:  # set and reset both go to `value` (reset defaults to 0)
                value = action.get('value', 0)
            low, high = action.get('min'), action.get('max')
            if action.get('wrap') and low is not None and high is not None and op in ('inc', 'dec'):
                value = low + (value - low) % (high - low + 1)
            else:
                if low is not None:
                    value = max(low, value)
                if high is not None:
                    value = min(high, value)
            value = max(-MAX_VALUE, min(MAX_VALUE, value))
            self.counters[name] = value
            self._dirty = True
            return value

    # --- timers ----------------------------------------------------------------------
    def apply_timer(self, action: dict) -> str:
        """Run one timer operation and return the timer's new state."""
        check_timer(action)
        name, op = action['name'], action.get('op', 'toggle')
        with self._lock:
            timer = self.timers.get(name)
            if timer is None and len(self.timers) >= MAX_TIMERS:
                raise ValueError('Too many timers')
            seconds = action.get('seconds') or (timer or {}).get('duration')
            now = self._clock()
            if op == 'toggle':
                op = {'running': 'pause', 'paused': 'resume'}.get((timer or {}).get('state'), 'start')
            if op == 'start':
                if not seconds:
                    raise ValueError('timer: start needs seconds')
                self.timers[name] = {'state': 'running', 'duration': seconds, 'remaining': float(seconds),
                                     'ends_at': now + seconds, 'notify': action.get('notify', ''),
                                     'sound': action.get('sound', False), 'actions': action.get('actions', [])}
            elif timer is None:
                raise ValueError(f'timer {name} has not been started')
            elif op == 'pause' and timer['state'] == 'running':
                timer.update(state='paused', remaining=max(0.0, timer['ends_at'] - now))
            elif op == 'resume' and timer['state'] == 'paused':
                timer.update(state='running', ends_at=now + timer['remaining'])
            elif op == 'stop':
                timer.update(state='idle', remaining=float(timer['duration']))
            self._dirty = True
            return self.timers[name]['state']

    def tick(self) -> list[dict]:
        """Finish timers whose time is up; returns what to announce for each."""
        finished = []
        with self._lock:
            now = self._clock()
            for name, timer in self.timers.items():
                if timer['state'] == 'running' and now >= timer['ends_at']:
                    timer.update(state='done', remaining=0.0)
                    self._dirty = True
                    finished.append({'name': name, 'message': timer['notify'] or f'Timer {name} finished',
                                     'sound': timer['sound'], 'actions': list(timer['actions'])})
        return finished

    def remaining(self, name: str) -> float | None:
        with self._lock:
            timer = self.timers.get(name)
            if timer is None:
                return None
            if timer['state'] == 'running':
                return max(0.0, timer['ends_at'] - self._clock())
            return 0.0 if timer['state'] == 'done' else timer['remaining']

    def is_running(self, name: str) -> bool:
        with self._lock:
            return self.timers.get(name, {}).get('state') == 'running'

    # --- values for labels and gauges ---------------------------------------------------
    def variables(self) -> dict[str, str]:
        with self._lock:
            values = {f'counter:{name}': str(value) for name, value in self.counters.items()}
            for name, timer in self.timers.items():
                state = timer['state']
                if state == 'done':
                    text = 'DONE'
                elif state == 'idle':
                    text = clock_text(float(timer['duration']))
                else:
                    text = clock_text(self.remaining(name) or 0)
                values[f'timer:{name}'] = text
                values[f'timer-state:{name}'] = state.upper()
            return values

    def raw(self) -> dict[str, float]:
        with self._lock:
            values = {f'counter:{name}': float(value) for name, value in self.counters.items()}
            values.update({f'timer:{name}': float(self.remaining(name) or 0) for name in self.timers})
            return values
