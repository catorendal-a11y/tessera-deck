#!/usr/bin/env python3
"""Tessera action engine and sole USB owner."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import struct
import sys
import threading
import time
import urllib.request
import zlib
import psutil
from control_api import ControlServer
from deck_assets import Assets
from host_runtime import InstanceLock, remember_port, resolve_port, session_locked
from system_stats import SystemStats, gauge_state

try:
    import serial
except ImportError:
    serial = None

IS_WINDOWS = os.name == 'nt'
VK = {'ctrl': 0x11, 'control': 0x11, 'shift': 0x10, 'alt': 0x12,
      'win': 0x5b, 'meta': 0x5b, 'enter': 13, 'return': 13, 'tab': 9,
      'esc': 27, 'escape': 27, 'space': 32, 'backspace': 8, 'delete': 46,
      'home': 36, 'end': 35, 'pageup': 33, 'pagedown': 34,
      'left': 37, 'up': 38, 'right': 39, 'down': 40,
      'comma': 0xbc, 'period': 0xbe, 'slash': 0xbf, 'grave': 0xc0,
      'lbracket': 0xdb, 'rbracket': 0xdd, 'minus': 0xbd, 'equals': 0xbb,
      'semicolon': 0xba, 'quote': 0xde, 'backslash': 0xdc,
      'insert': 45, 'printscreen': 44, 'apps': 0x5d, 'capslock': 20,
      'volumemute': 0xad, 'volumedown': 0xae, 'volumeup': 0xaf,
      'playpause': 0xb3, 'medianext': 0xb0, 'mediaprev': 0xb1, 'mediastop': 0xb2}
VK.update({c: ord(c.upper()) for c in 'abcdefghijklmnopqrstuvwxyz0123456789'})
VK.update({f'numpad{i}': 0x60 + i for i in range(10)})
VK.update({f'f{i}': 0x6f + i for i in range(1, 25)})
# Navigation keys must carry KEYEVENTF_EXTENDEDKEY or some apps read them as numpad keys.
EXTENDED_VK = frozenset({33, 34, 35, 36, 37, 38, 39, 40, 44, 45, 46, 0x5b, 0x5d})
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 1, 2


def parse_hotkey(combo):
    parts = [p.strip().lower() for p in combo.split('+')]
    if not parts or any(p not in VK for p in parts):
        raise ValueError(f'Unknown hotkey: {combo!r}')
    return [VK[p] for p in parts]


def dry_hotkey(combo):
    try:
        parse_hotkey(combo)
        return True, combo.split('+')
    except ValueError:
        return False, combo.split('+')


if IS_WINDOWS:
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
                    ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                    ('dwExtraInfo', ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                    ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                    ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]

    class INPUTUNION(ctypes.Union):
        _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ('u',)
        _fields_ = [('type', wintypes.DWORD), ('u', INPUTUNION)]

    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                  wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _key(vk=0, scan=0, flags=0):
    if not IS_WINDOWS:
        raise OSError('Hurtigtaster og tekst krever Windows')
    value = INPUT(type=1)
    value.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    if user32.SendInput(1, ctypes.byref(value), ctypes.sizeof(value)) != 1:
        raise OSError('Windows avviste tastetrykket (kontroller appens rettigheter)')


def _extended_flag(vk):
    return KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VK else 0


def send_hotkey(combo):
    pressed = []
    try:
        for vk in parse_hotkey(combo):
            _key(vk=vk, flags=_extended_flag(vk))
            pressed.append(vk)
    finally:
        for vk in reversed(pressed):
            _key(vk=vk, flags=KEYEVENTF_KEYUP | _extended_flag(vk))


def send_text(text):
    raw = text.encode('utf-16-le')
    for i in range(0, len(raw), 2):
        code = int.from_bytes(raw[i:i+2], 'little')
        _key(scan=code, flags=4)
        _key(scan=code, flags=6)


def foreground_context():
    if not IS_WINDOWS:
        return {'exe': '', 'title': '', 'processes': []}
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return {'exe': '', 'title': '', 'processes': []}
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    length = min(max(user32.GetWindowTextLengthW(hwnd), 0), 4096)
    title_buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
    title = title_buffer.value.lower()
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return {'exe': '', 'title': title, 'processes': []}
    exe = ''
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            exe = os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(handle)
    processes = [exe] if exe else []
    try:
        for child in psutil.Process(pid.value).children(recursive=True):
            name = child.name().lower()
            if name and name not in processes:
                processes.append(name)
    except (psutil.Error, OSError):
        pass
    return {'exe': exe, 'title': title, 'processes': processes}


def foreground_exe():
    """Compatibility helper used by integrations that only need the executable."""
    return foreground_context()['exe']


def focus_existing_process(process_name):
    """Restore the first visible window owned by process_name."""
    if not IS_WINDOWS or not process_name:
        return False
    wanted = process_name.lower()
    pids = set()
    try:
        for process in psutil.process_iter(['pid', 'name']):
            if (process.info.get('name') or '').lower() == wanted:
                pids.add(process.info['pid'])
    except (psutil.Error, OSError):
        return False
    if not pids:
        return False
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in pids and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(visit, 0)
    if not found:
        return False
    user32.ShowWindow(found[0], 9)
    user32.SetForegroundWindow(found[0])
    return True


def matches_foreground(pattern, context):
    """Match a foreground executable, terminal child process, or window title."""
    pattern = pattern.strip().lower()
    if pattern.startswith('title:'):
        return pattern.removeprefix('title:').strip() in context.get('title', '').lower()
    if pattern.startswith('process:'):
        pattern = pattern.removeprefix('process:').strip()
    return pattern in {name.lower() for name in context.get('processes', [])}


ACTION_FIELDS = {'hotkey': 'keys', 'text': 'text', 'open': 'target', 'shell': 'command',
                 'http': 'url', 'delay': None, 'page': 'page', 'profile': 'profile',
                 'press': 'id', 'set': 'variable',
                 'folder': 'page', 'back': None, 'home': None, 'state': 'button'}
HTTP_METHODS = ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')
DEFAULT_DIM_AFTER = 300  # seconds of no presses before the panel dims
CLOCK_INTERVAL = 600  # seconds between PC clock updates for panels without Wi-Fi
UNSET_VARIABLE = re.compile(r'[$][(]var:[A-Za-z0-9_.-]+[)]')
VARIABLE_NAME = re.compile(r'[A-Za-z0-9_.-]{1,64}')
COLOR_PATTERN = re.compile(r'#[0-9a-fA-F]{6}')
TIME_PATTERN = re.compile(r'(?:[01]\d|2[0-3]):[0-5]\d')
TRIGGER_KINDS = ('startup', 'interval', 'daily', 'file', 'variable')


def _check_action(action, pages, profiles):
    if not isinstance(action, dict) or action.get('type') not in ACTION_FIELDS:
        raise ValueError('Unknown action')
    kind = action['type']
    field = ACTION_FIELDS[kind]
    if field and field not in action:
        raise ValueError(f'{kind} is missing {field}')
    if field and kind not in ('press', 'state') and not isinstance(action[field], str):
        raise ValueError(f'{kind}: {field} must be text')
    if kind == 'press' and (type(action['id']) is not int or not 1 <= action['id'] <= 18):
        raise ValueError('press: id must be 1..18')
    if kind == 'state':
        _check_state_action(action)
    if kind == 'hotkey':
        parse_hotkey(action['keys'])
    if kind == 'open' and (type(action.get('reuse', False)) is not bool
                           or not isinstance(action.get('process', ''), str)
                           or len(action.get('process', '')) > 260):
        raise ValueError('Invalid program setting')
    if kind in ('page', 'folder') and action['page'] not in pages:
        raise ValueError(f'Unknown page: {action["page"]}')
    if kind == 'profile' and action['profile'] not in profiles:
        raise ValueError(f'Unknown profile: {action["profile"]}')
    if kind == 'delay' and (type(action.get('ms', 100)) is not int
                            or not 0 <= action.get('ms', 100) <= 60000):
        raise ValueError('delay must be 0..60000 ms')
    if kind in ('shell', 'http'):
        timeout = action.get('timeout', 5)
        if type(timeout) not in (int, float) or not 0 < timeout <= 300:
            raise ValueError('timeout must be between 0 and 300 seconds')
    if kind == 'http':
        _check_http(action)


def _check_state_action(action):
    if type(action['button']) is not int or not 1 <= action['button'] <= 18:
        raise ValueError('state: button must be 1..18')
    value = action.get('state', 'next')
    if value != 'next' and (type(value) is not int or not 0 <= value <= 7):
        raise ValueError("state: state must be 'next' or 0..7")


def _check_http(action):
    headers = action.get('headers', {})
    if (action.get('method', 'GET') not in HTTP_METHODS
            or not isinstance(headers, dict)
            or any(not isinstance(key, str) or not isinstance(value, str)
                   for key, value in headers.items())
            or not isinstance(action.get('body', ''), str)):
        raise ValueError('Invalid HTTP setup')


def _check_actions(actions, pages, profiles):
    if not isinstance(actions, list):
        raise ValueError('actions must be a list')
    for action in actions:
        _check_action(action, pages, profiles)


def _check_color(value, message):
    if not isinstance(value, str) or not COLOR_PATTERN.fullmatch(value):
        raise ValueError(message)


def _check_status(status):
    if not isinstance(status, dict) or not isinstance(status.get('var'), str) or not VARIABLE_NAME.fullmatch(status['var']):
        raise ValueError('status needs a variable name')
    colors = status.get('colors', {})
    if not isinstance(colors, dict) or any(not isinstance(value, str) or not COLOR_PATTERN.fullmatch(value)
                                           for value in colors.values()):
        raise ValueError('status.colors must map values to #RRGGBB colors')


GAUGE_FORMATS = ('int', 'ghz', 'gb', 'rate', 'uptime', 'live')


def _check_gauge(gauge):
    if not isinstance(gauge, dict) or not isinstance(gauge.get('key'), str) or not gauge['key']:
        raise ValueError('gauge needs a sensor key')
    for name in ('max', 'warn', 'critical'):
        value = gauge.get(name)
        if name in gauge and (type(value) not in (int, float) or (name == 'max' and value <= 0)):
            raise ValueError(f'gauge.{name} must be a number' + (' above 0' if name == 'max' else ''))
    if gauge.get('fmt', 'int') not in GAUGE_FORMATS or gauge.get('scale', 'linear') not in ('linear', 'log'):
        raise ValueError('Invalid gauge format or scale')
    if not isinstance(gauge.get('unit', ''), str) or len(gauge.get('unit', '')) > 3:
        raise ValueError('gauge.unit must be at most 3 characters')
    if 'percent_key' in gauge and not isinstance(gauge['percent_key'], str):
        raise ValueError('gauge.percent_key must be text')


def _check_button(button, pages, profiles):
    if not isinstance(button.get('label'), str) or not button['label'].strip():
        raise ValueError('The button needs a name')
    if not isinstance(button.get('icon', 'ok'), str) or len(button.get('icon', 'ok')) > 100:
        raise ValueError('Invalid button icon')
    _check_color(button.get('color', '#35D07F'), 'Invalid button color')
    if 'gauge' in button:
        _check_gauge(button['gauge'])
    if 'status' in button:
        _check_status(button['status'])
    _check_actions(button.get('actions', []), pages, profiles)
    states = button.get('states', [])
    if not isinstance(states, list) or len(states) > 8 or (states and len(states) < 2):
        raise ValueError('A toggle button needs 2-8 states')
    for state in states:
        if not isinstance(state, dict):
            raise ValueError('Invalid button state')
        _check_actions(state.get('actions', []), pages, profiles)
        _check_color(state.get('color', '#35D07F'), 'Invalid state color')
    title = button.get('title', {})
    if (not isinstance(title, dict) or title.get('size', 16) not in (16, 20, 24, 28)
            or title.get('position', 'bottom') not in ('top', 'middle', 'bottom', 'hidden')):
        raise ValueError('Invalid text setting')


def _check_button_list(name, buttons, pages, profiles):
    if not isinstance(buttons, list) or not 0 <= len(buttons) <= 18:
        raise ValueError(f'{name}: use 0..18 buttons')
    ids = set()
    for button in buttons:
        if not isinstance(button, dict):
            raise ValueError('Each button must be an object')
        bid = button.get('id')
        if type(bid) is not int or not 1 <= bid <= 18 or bid in ids:
            raise ValueError(f'{name}: invalid or duplicate id')
        ids.add(bid)
        _check_button(button, pages, profiles)


def _check_profile(name, profile, profiles):
    pages = profile.get('pages') if isinstance(profile, dict) else None
    if not isinstance(pages, dict) or not pages:
        raise ValueError(f'{name} has no pages')
    patterns = profile.get('match', [])
    if not isinstance(patterns, list) or any(not isinstance(p, str) or not p.strip() for p in patterns):
        raise ValueError('match must be a list of program names')
    if any(not isinstance(page, str) or not page.strip() or len(page) > 100 for page in pages):
        raise ValueError('Page names must be 1-100 characters')
    for page_name, buttons in list(pages.items()) + [('Pinned buttons', profile.get('pinned', []))]:
        _check_button_list(page_name, buttons, pages, profiles)


def _check_trigger(trigger, pages, profiles):
    spec = trigger.get('when', {}) if isinstance(trigger, dict) else None
    if not isinstance(spec, dict):
        raise ValueError('Invalid trigger')
    kind = spec.get('type')
    if kind not in TRIGGER_KINDS:
        raise ValueError('Unknown trigger')
    if kind == 'interval' and (type(spec.get('seconds')) is not int or spec['seconds'] < 1):
        raise ValueError('interval needs seconds > 0')
    at = spec.get('at', '')
    if kind == 'daily' and not (isinstance(at, str) and TIME_PATTERN.fullmatch(at)):
        raise ValueError('daily needs at as HH:MM')
    if kind in ('file', 'variable') and not spec.get('path' if kind == 'file' else 'name'):
        raise ValueError('Trigger is missing a path or variable name')
    _check_actions(trigger.get('actions', []), pages, profiles)


def _check_display(display):
    if not isinstance(display, dict):
        raise ValueError('display must be an object')
    limits = {'brightness': (1, 100), 'dim_after': (0, 86400), 'dim_level': (0, 100)}
    for key, value in display.items():
        if key not in limits:
            raise ValueError(f'Unknown display setting: {key}')
        low, high = limits[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'display.{key} must be a whole number from {low} to {high}')


def _validate_config(config):
    profiles = config.get('profiles') if isinstance(config, dict) else None
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError('The configuration needs at least one profile')
    if config.get('default_profile', next(iter(profiles))) not in profiles:
        raise ValueError('Unknown default profile')
    if any(not isinstance(name, str) or not name.strip() or len(name) > 100 for name in profiles):
        raise ValueError('Profile names must be 1-100 characters')
    for name, profile in profiles.items():
        _check_profile(name, profile, profiles)
    if type(config.get('auto_profiles', True)) is not bool:
        raise ValueError('auto_profiles must be on or off')
    _check_display(config.get('display', {}))
    triggers = config.get('triggers', [])
    if not isinstance(triggers, list):
        raise ValueError('triggers must be a list')
    # Triggers run in the active profile, so any profile's page is a valid target.
    all_pages = {page for profile in profiles.values() for page in profile['pages']}
    for trigger in triggers:
        _check_trigger(trigger, all_pages, profiles)
    return config


def validate_config(config):
    """Validate a config; every malformed input surfaces as ValueError."""
    try:
        return _validate_config(config)
    except (TypeError, AttributeError, KeyError, RecursionError) as exc:
        raise ValueError(f'Invalid configuration: {exc}') from exc


class PanelSerial:
    """Serialized writes and byte-based framing retain split UTF-8 and newlines."""
    def __init__(self, port, log):
        if serial is None:
            raise RuntimeError('Install host/requirements.txt first')
        self.log = log
        self.write_lock = threading.RLock()
        self.rx = bytearray()
        self.cfg_done = threading.Event()
        self.cfg_reply = ''
        self.asset_done = threading.Event()
        self.asset_reply = ''
        self.assets_sent = set()
        self.ser = serial.Serial()
        self.ser.port, self.ser.baudrate = port, 115200
        self.ser.timeout, self.ser.write_timeout = 0.1, 2
        self.ser.dtr = self.ser.rts = False
        self.ser.open()

    def close(self):
        self.ser.close()

    def send_line(self, text):
        raw = (text + '\n').encode('utf-8')
        with self.write_lock:
            if self.ser.write(raw) != len(raw):
                raise OSError('Ufullstendig USB-skriving')

    def read_lines(self):
        self.rx.extend(self.ser.read(max(1, min(self.ser.in_waiting, 4096))))
        if len(self.rx) > 32768:
            self.rx.clear()
            raise OSError('For lang USB-melding')
        result = []
        while (end := self.rx.find(b'\n')) >= 0:
            result.append(bytes(self.rx[:end]).decode('utf-8', 'replace').strip())
            del self.rx[:end + 1]
        return result

    def push_buttons(self, buttons):
        payload = json.dumps({'buttons': buttons}, ensure_ascii=True, separators=(',', ':'))
        if len(payload.encode()) > 8192:
            raise ValueError('The button layout is too large')
        with self.write_lock:
            self.cfg_done.clear()
            self.send_line('AD_CFG_BEGIN')
            for i in range(0, len(payload), 380):
                self.send_line('AD_CFG_DATA ' + payload[i:i+380])
            self.send_line('AD_CFG_END')
            if not self.cfg_done.wait(4):
                raise TimeoutError('The panel did not acknowledge the button layout')
            if not self.cfg_reply.startswith('AD_CFG_END OK'):
                raise ValueError(self.cfg_reply)

    def feedback(self, button_id, ok):
        # A touch proves the panel is alive. Wake the backlight as part of the
        # response so a dark display can recover without a cable reconnect.
        self.send_line('AD_DISPLAY_WAKE')
        self.send_line(f'AD_FEEDBACK {"ok" if ok else "alert"} {button_id}')

    def push_assets(self, buttons, assets):
        for name in sorted({b.get('icon', '') for b in buttons if b.get('icon', '').startswith('im:')}):
            if name in self.assets_sent:
                continue
            raw = assets.read(name)
            with self.write_lock:
                self.asset_done.clear()
                self.asset_reply = ''
                self.send_line(f'AD_IMG_BEGIN {name} {len(raw)} {zlib.crc32(raw)}')
                # USB Serial/JTAG accepts large writes, but the firmware task
                # consumes line frames in smaller bursts. Pace image chunks so
                # Windows cannot overrun that receive loop on detailed icons.
                for offset in range(0, len(raw), 160):
                    self.send_line(f'AD_IMG_DATA {offset} ' + raw[offset:offset+160].hex())
                    self.ser.flush()
                    time.sleep(.01)
                self.send_line('AD_IMG_END')
                if not self.asset_done.wait(15):
                    raise TimeoutError('The panel did not acknowledge the image')
                if self.asset_reply != 'AD_IMG_END OK ' + name:
                    raise ValueError(self.asset_reply)
                self.assets_sent.add(name)

class Daemon:
    def __init__(self, args, panel_factory=PanelSerial):
        self.args = args
        self.config = self.load_profiles(args.profiles)
        self.profile = self.config.get('default_profile', next(iter(self.config['profiles'])))
        self.page = next(iter(self.config['profiles'][self.profile]['pages']))
        self.auto_profile = None
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
        self.jobs = queue.Queue(maxsize=128)
        self.state_lock = threading.RLock()
        self.panel_factory = panel_factory
        self.panel = None
        self.connection_failed = threading.Event()
        self.active_press = []
        self.state_set_by_action = set()
        self.folder_stack = []
        self.button_states = {}
        self.profile_stamp = Path(args.profiles).stat().st_mtime_ns
        self.runtime_path = Path(args.profiles).with_name('deck-runtime.local.json')
        self.runtime_written = 0.0
        self.foreground = {'exe': '', 'title': '', 'processes': []}
        self.agents = {'codex': False, 'claude': False, 'zcode': False}
        self.agent_scan_at = 0.0
        self.stats = SystemStats()
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
            return validate_config(json.load(stream))

    def log(self, message):
        print(f'[{time.strftime("%H:%M:%S")}] {message}', flush=True)

    def publish_runtime(self, connected, error=None, force=False):
        now = time.time()
        if not force and now - self.runtime_written < 1.5:
            return
        buttons = self.current_buttons()
        gauges = {str(item['id']): dict(item['gauge'], color=item['color']) for item in buttons if 'gauge' in item}
        state = {'pid': os.getpid(), 'updated': now, 'connected': bool(connected),
                 'port': self.port, 'profile': self.profile, 'page': self.page, 'gauges': gauges,
                 'dimmed': self.dimmed,
                 'buttons': len(buttons), 'error': str(error)[:180] if error else None,
                 'foreground': self.foreground.get('exe', ''), 'auto_profile': self.auto_profile,
                 'agents': self.agents, 'stats': self.stats.display, 'vars': self.custom_vars,
                 'last_action': self.last_action}
        temporary = self.runtime_path.with_suffix('.tmp')
        try:
            temporary.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, self.runtime_path)
            self.runtime_written = now
        except OSError:
            pass

    def variables(self):
        return dict(time=time.strftime('%H:%M'), date=time.strftime('%d.%m'),
                    profile=self.profile, page=self.page,
                    **{f'agent:{name}': 'ON' if running else 'OFF'
                       for name, running in self.agents.items()},
                    **{f'stat:{name}': value for name, value in self.stats.display.items()},
                    **{f'var:{k}': str(v) for k, v in self.custom_vars.items()})

    def substitute(self, text):
        for key, value in self.variables().items():
            text = text.replace(f'$({key})', value)
        return UNSET_VARIABLE.sub('', text)  # a variable nobody has set yet renders empty

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
            entry = dict(
                id=button['id'], label=label.encode('utf-8')[:24].decode('utf-8', 'ignore'),
                icon=self.resolve_icon(button), color=color, title=button.get('title', {}))
            if isinstance(button.get('gauge'), dict):
                state = gauge_state(button['gauge'], self.stats.raw, color)
                entry.update(color=state['color'], gauge={'p': state['p'], 't': state['t']})
            result.append(entry)
        return result

    def display_settings(self):
        display = self.config.get('display', {})
        return {'brightness': display.get('brightness', 100),
                'dim_after': display.get('dim_after', DEFAULT_DIM_AFTER),
                'dim_level': display.get('dim_level', 10)}

    def apply_brightness(self):
        self.panel.send_line(f'AD_BRIGHTNESS {self.display_settings()["brightness"]}')
        self.dimmed = False

    def wake_display(self):
        self.last_activity = time.monotonic()
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

    def idle_tick(self, now):
        """Dim the panel once after dim_after seconds without a press."""
        settings = self.display_settings()
        if (not settings['dim_after'] or self.dimmed or self.panel is None
                or now - self.last_activity < settings['dim_after']):
            return
        self.dim_display(f'after {settings["dim_after"]} s without a press')

    def push_page(self, force=False):
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
            self.pushed_labels = [entry for entry in self.pushed_labels if entry[0] == path][-1:] + [(path, labels)]
            self.log(f'{self.profile} / {self.page}: {len(buttons)} buttons acknowledged')

    def switch_page(self, page, folder=False):
        if page not in self.config['profiles'][self.profile]['pages']:
            raise ValueError(f'Unknown page: {page}')
        if folder:
            if len(self.folder_stack) >= 16:
                raise ValueError('Folders are nested more than 16 levels deep')
            self.folder_stack.append(self.page)
        else:
            self.folder_stack.clear()
        self.page = page
        self.push_page(force=True)
        return True

    def switch_profile(self, profile, auto=False):
        if profile not in self.config['profiles']:
            raise ValueError(f'Unknown profile: {profile}')
        if profile != self.profile:
            self.folder_stack.clear()
            self.profile = profile
            self.page = next(iter(self.config['profiles'][profile]['pages']))
            self.push_page()
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
            send_hotkey(action['keys'])
        elif kind == 'text':
            send_text(self.substitute(action['text']))
        elif kind == 'open':
            target = self.substitute(action['target'])
            if IS_WINDOWS:
                process = action.get('process', '')
                if not (action.get('reuse', False) and focus_existing_process(process)):
                    os.startfile(os.path.expandvars(target))
            else:
                subprocess.Popen(['xdg-open', target])
        elif kind == 'shell':
            result = subprocess.run(self.substitute(action['command']), shell=True,
                                    timeout=action.get('timeout', 30), check=False,
                                    creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0)
            if result.returncode:
                raise RuntimeError(f'Kommando avsluttet med kode {result.returncode}')
        elif kind == 'http':
            request = urllib.request.Request(self.substitute(action['url']),
                method=action.get('method', 'GET'), headers=action.get('headers', {}),
                data=self.substitute(action.get('body', '')).encode() or None)
            with urllib.request.urlopen(request, timeout=action.get('timeout', 5)) as response:
                response.read(65536)
        elif kind == 'delay':
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
        elif kind == 'press':
            if not self.dispatch_press(int(action['id'])):
                raise ValueError('The child button failed')
        elif kind == 'state':
            self.set_button_state(action['button'], action.get('state', 'next'))
        elif kind == 'set':
            self.custom_vars[action['variable']] = self.substitute(str(action.get('value', '')))
            self.push_page()
        else:
            raise ValueError(f'Unknown action: {kind}')
        return True

    def dispatch_press(self, button_id):
        identity = (self.profile, self.page, button_id)
        if identity in self.active_press or len(self.active_press) >= 16:
            raise ValueError('Circular button action')
        buttons = self.effective_buttons()
        button = next((b for b in buttons if b['id'] == button_id), None)
        if button is None:
            self.last_action = {'id': button_id, 'label': 'Unknown button', 'ok': False,
                                'error': 'The button does not exist on the active page', 'at': time.time()}
            self.panel.feedback(button_id, False)
            self.publish_runtime(True, force=True)
            return False
        if not self.active_press:
            self.state_set_by_action.clear()
        self.active_press.append(identity)
        state_key = self.state_key(button)
        resolved = self.resolved_button(button)
        ok, error = False, ''
        try:
            self.log(f'Button {button_id}: {button["label"]}')
            for action in resolved.get('actions', []):
                if self.stop.is_set():
                    raise RuntimeError('Stopping')
                self.run_action(action)
            if button.get('states') and state_key not in self.state_set_by_action:
                self.button_states[state_key] = (self.button_states.get(state_key, 0) + 1) % len(button['states'])
                self.push_page()
            ok = True
        except Exception as exc:
            error = str(exc)[:180]
            self.log(f'Action failed: {exc}')
        finally:
            self.active_press.pop()
            self.last_action = {'id': button_id, 'label': button['label'], 'ok': ok,
                                'error': error or None, 'at': time.time()}
            try:
                self.panel.feedback(button_id, ok)
            finally:
                self.publish_runtime(True, force=True)
        return ok

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
        except (OSError, ValueError, AttributeError):
            pass  # the reader loop reports the disconnect

    def enqueue(self, job):
        try:
            self.jobs.put_nowait(job)
        except queue.Full:
            self.log('The action queue is full; the press was rejected')

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
                                self.enqueue(('press', message['button'], message.get('label')))
                        elif message.get('type') == 'wake':
                            self.enqueue(('panel-woke',))
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
            self.last_activity = time.monotonic()
            current = next((b for b in self.current_buttons() if b['id'] == job[1]), None)
            path = (self.profile, self.page)
            shown = job[2] is None or job[2] == (current or {}).get('label') or any(
                entry_path == path and labels.get(job[1]) == job[2] for entry_path, labels in self.pushed_labels)
            if current and shown:
                self.dispatch_press(job[1])
        elif kind == 'profile':
            self.switch_profile(job[1], auto=True)
        elif kind == 'page':
            self.switch_page(job[1])
        elif kind == 'actions':
            for action in job[1]:
                self.run_action(action)
        elif kind == 'push':
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
            self.dispatch_press(job[1])
        elif kind == 'dim':
            self.dim_display('by request')
        elif kind == 'wake':
            self.wake_display()
        elif kind == 'panel-woke':
            # The panel already restored its backlight after a touch.
            self.last_activity = time.monotonic()
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
                    if not (self.connection_failed.is_set() or self.panel is None):
                        self.handle_job(job)
            except Exception as exc:
                self.log(f'Action failed: {exc}')
            finally:
                self.jobs.task_done()

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
                except OSError:
                    continue
                fire = before is not None and before != value
            elif kind == 'variable':
                value = self.custom_vars.get(spec['name'])
                fire = value is not None and before != value
            self.trigger_state[index] = value
            if fire:
                # Each trigger fires once; triggers of the same type are independent.
                self.enqueue(('actions', trigger.get('actions', [])))

    def focus_tick(self):
        if self.args.no_focus or not self.config.get('auto_profiles', True):
            return
        context = foreground_context()
        self.foreground = context
        if not context.get('exe'):
            return
        if self.manual_focus_exe:
            if context['exe'] == self.manual_focus_exe:
                return
            self.manual_focus_exe = ''
        match = next((name for name, p in self.config['profiles'].items()
                      if any(matches_foreground(pattern, context) for pattern in p.get('match', []))), None)
        if match:
            if match != self.profile:
                self.auto_profile = match
                self.enqueue(('profile', match))
        elif self.auto_profile is not None:
            self.auto_profile = None
            self.enqueue(('profile', self.config.get('default_profile', next(iter(self.config['profiles'])))))

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
            self.config = config
            if self.profile not in config['profiles']:
                self.profile = config.get('default_profile', next(iter(config['profiles'])))
            if self.page not in config['profiles'][self.profile]['pages']:
                self.page = next(iter(config['profiles'][self.profile]['pages']))
            self.trigger_state.clear()
            self.folder_stack.clear()
            self.button_states.clear()
            self.enqueue(('force-push',))
            self.enqueue(('brightness',))

    def run(self):
        threading.Thread(target=self.worker_loop, daemon=True).start()
        self.api = ControlServer(self, Path(self.args.profiles).with_name('deck-api.local.json'))
        self.api.start()
        # Standalone Deck host: the USB owner only handles buttons and assets.
        startup_fired = False
        try:
            while not self.stop.is_set():
                stop_path = Path(__file__).with_name('deck-stop.local.json')
                if stop_path.exists():
                    try:
                        if json.loads(stop_path.read_text(encoding='utf-8')).get('pid') == os.getpid():
                            self.stop.set()
                            continue
                    except (ValueError, OSError):
                        pass
                if self.panel is None or self.connection_failed.is_set():
                    if self.panel:
                        self.panel.close()
                    self.panel = None
                    try:
                        self.port = resolve_port(self.args.port, self.device_state_path)
                        self.panel = self.panel_factory(self.port, self.log)
                        remember_port(self.port, self.device_state_path)
                        self.connection_failed.clear()
                        threading.Thread(target=self.reader_loop, args=(self.panel,), daemon=True).start()
                        self.clock_sent_at = float('-inf')
                        threading.Thread(target=self.heartbeat_loop, args=(self.panel,), daemon=True).start()
                        with self.state_lock:
                            self.last_activity = time.monotonic()
                            self.apply_brightness()
                            self.push_page(force=True)
                        self.publish_runtime(True, force=True)
                        self.log(f'USB ready on {self.port}')
                        if not startup_fired:
                            self.fire_trigger({'type': 'startup'})
                            startup_fired = True
                    except (OSError, ValueError, TimeoutError) as exc:
                        self.log(f'USB: {exc}; retrying in 2 seconds')
                        self.publish_runtime(False, exc, force=True)
                        self.connection_failed.set()
                        self.stop.wait(2)
                        continue
                now = time.monotonic()
                for tick in (lambda: self.agent_tick(now), lambda: self.stats_tick(now),
                             self.focus_tick, self.reload_profiles):
                    try:
                        tick()
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
                    except (OSError, ValueError):
                        pass
                with self.state_lock:
                    self.trigger_tick(time.monotonic())
                    self.lock_tick(session_locked())
                    self.idle_tick(time.monotonic())
                self.publish_runtime(self.panel is not None and not self.connection_failed.is_set())
                self.enqueue(('push',))
                self.stop.wait(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop.set()
            self.api.stop()
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
