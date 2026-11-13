"""Validation of profiles.json: every malformed configuration surfaces as ValueError before the engine uses it."""
import json
import math
import re

from ambient import check_ambient
import calendar_feed
from config_store import CONFIG_VERSION, version_of
from live_state import NAME as LIVE_NAME, check_counter, check_timer
import widgets
from pc_state import FLAG_SOURCES, check_audio
from plugins import PLUGIN_ID, check_plugin_config
from substitution import check_web_url
from win_input import MOUSE_OPERATIONS, WINDOW_OPERATIONS, parse_hotkey

ACTION_FIELDS = {'hotkey': 'keys', 'text': 'text', 'open': 'target', 'shell': 'command',
                 'http': 'url', 'delay': None, 'page': 'page', 'profile': 'profile',
                 'press': 'id', 'set': 'variable', 'audio': 'target', 'counter': 'name', 'timer': 'name', 'plugin': 'plugin', 'mouse': 'op', 'screen': 'show',
                 'folder': 'page', 'back': None, 'home': None, 'state': 'button', 'profile_lock': None,
                 'clipboard': 'text', 'window': 'op', 'toggle': 'variable', 'panel_lock': None}
HTTP_METHODS = ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')
VARIABLE_NAME = re.compile(r'[A-Za-z0-9_.-]{1,64}')
COLOR_PATTERN = re.compile(r'#[0-9a-fA-F]{6}')
TIME_PATTERN = re.compile(r'(?:[01]\d|2[0-3]):[0-5]\d')
TRIGGER_KINDS = ('startup', 'interval', 'daily', 'file', 'variable')


def _check_press(action, pages, profiles):
    if type(action['id']) is not int or not 1 <= action['id'] <= 18:
        raise ValueError('press: id must be 1..18')


def _check_hotkey(action, pages, profiles):
    parse_hotkey(action['keys'])


def _check_open(action, pages, profiles):
    if (type(action.get('reuse', False)) is not bool or not isinstance(action.get('process', ''), str)
            or len(action.get('process', '')) > 260):
        raise ValueError('Invalid program setting')


def _check_page(action, pages, profiles):
    if action['page'] not in pages:
        raise ValueError(f'Unknown page: {action["page"]}')


def _check_profile_action(action, pages, profiles):
    if action['profile'] not in profiles:
        raise ValueError(f'Unknown profile: {action["profile"]}')


def _check_text(action, pages, profiles):
    if type(action.get('delay_ms', 0)) is not int or not 0 <= action.get('delay_ms', 0) <= 500:
        raise ValueError('text: delay_ms must be a whole number from 0 to 500')


def _check_mouse(action, pages, profiles):
    if action['op'] not in MOUSE_OPERATIONS:
        raise ValueError(f'mouse: op must be one of {", ".join(MOUSE_OPERATIONS)}')
    for key, low, high in (('x', -20000, 20000), ('y', -20000, 20000), ('amount', -50, 50)):
        if key in action and (type(action[key]) is not int or not low <= action[key] <= high):
            raise ValueError(f'mouse: {key} must be a whole number from {low} to {high}')
    # A monitor left of or above the main one has negative positions, and send_mouse maps over the whole desktop.
    if action['op'] == 'moveto' and ('x' not in action or 'y' not in action):
        raise ValueError('mouse: moveto needs x and y screen positions')


def _check_plugin(action, pages, profiles):
    args = action.get('args', {})
    if (not PLUGIN_ID.fullmatch(action['plugin']) or not isinstance(action.get('command'), str)
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', action['command']) or not isinstance(args, dict)
            or len(json.dumps(args)) > 1024):
        raise ValueError('plugin: needs a plugin id, a command name and small arguments')


def _check_clipboard(action, pages, profiles):
    if type(action.get('paste', False)) is not bool:
        raise ValueError('clipboard: paste must be true or false')


def _check_window(action, pages, profiles):
    process = action.get('process', '')
    if action['op'] not in WINDOW_OPERATIONS:
        raise ValueError(f'window: op must be one of {", ".join(WINDOW_OPERATIONS)}')
    if not isinstance(process, str) or len(process) > 260:
        raise ValueError('window: process must be a program name like notepad.exe')
    if action['op'] == 'focus' and not process.strip():
        raise ValueError('window: focus needs a process name')


def _check_toggle(action, pages, profiles):
    # Flips a variable between two values; a toggle key's own states (states + 'state' actions) cover alternating lists.
    values = action.get('values', ['on', 'off'])
    if not VARIABLE_NAME.fullmatch(action['variable']):
        raise ValueError('toggle: variable must be 1-64 letters, digits, _ . or -')
    if (not isinstance(values, list) or len(values) != 2 or any(not isinstance(v, str) or len(v) > 64 for v in values)
            or values[0] == values[1]):
        raise ValueError('toggle: values must be two different texts')


SCREEN_CHOICES = ('clock', 'keys', 'toggle')


def _check_screen(action, pages, profiles):
    if action['show'] not in SCREEN_CHOICES:
        raise ValueError(f'screen: show must be one of {", ".join(SCREEN_CHOICES)}')


PANEL_LOCK_MODES = ('toggle', 'on', 'off')


def _check_panel_lock(action, pages, profiles):
    if action.get('mode', 'toggle') not in PANEL_LOCK_MODES:
        raise ValueError(f'panel_lock: mode must be one of {", ".join(PANEL_LOCK_MODES)}')


def _check_counter(action, pages, profiles):
    check_counter(action)


def _check_timer_action(action, pages, profiles):
    check_timer(action)
    _check_actions(action.get('actions', []), pages, profiles)


def _check_audio(action, pages, profiles):
    check_audio(action)


def _check_delay(action, pages, profiles):
    if type(action.get('ms', 100)) is not int or not 0 <= action.get('ms', 100) <= 60000:
        raise ValueError('delay must be 0..60000 ms')


def _check_timeout(action):
    timeout = action.get('timeout', 5)
    if type(timeout) not in (int, float) or not 0 < timeout <= 300:
        raise ValueError('timeout must be between 0 and 300 seconds')


def _check_shell(action, pages, profiles):
    _check_timeout(action)


def _check_http_action(action, pages, profiles):
    _check_timeout(action)
    _check_http(action)


def _check_state_kind(action, pages, profiles):
    _check_state_action(action)


ACTION_CHECKS = {'press': _check_press, 'state': _check_state_kind, 'hotkey': _check_hotkey, 'open': _check_open,
                 'page': _check_page, 'folder': _check_page, 'profile': _check_profile_action, 'text': _check_text,
                 'mouse': _check_mouse, 'screen': _check_screen, 'plugin': _check_plugin, 'counter': _check_counter,
                 'timer': _check_timer_action, 'audio': _check_audio, 'delay': _check_delay,
                 'shell': _check_shell, 'http': _check_http_action, 'clipboard': _check_clipboard,
                 'window': _check_window, 'toggle': _check_toggle, 'panel_lock': _check_panel_lock}


def _check_action(action, pages, profiles):
    if not isinstance(action, dict) or action.get('type') not in ACTION_FIELDS:
        raise ValueError('Unknown action')
    kind = action['type']
    field = ACTION_FIELDS[kind]
    if field and field not in action:
        raise ValueError(f'{kind} is missing {field}')
    if field and kind not in ('press', 'state') and not isinstance(action[field], str):
        raise ValueError(f'{kind}: {field} must be text')
    check = ACTION_CHECKS.get(kind)
    if check:
        check(action, pages, profiles)


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
    url = action['url']
    if not url.startswith('$('):  # an address built from a variable is checked again when it runs
        check_web_url(url)


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


GAUGE_MIN_MAX = 1e-6
GAUGE_FORMATS = ('int', 'ghz', 'gb', 'rate', 'uptime', 'live', 'clock')


def _check_gauge(gauge):
    if not isinstance(gauge, dict) or not isinstance(gauge.get('key'), str) or not gauge['key']:
        raise ValueError('gauge needs a sensor key')
    for name in ('max', 'warn', 'critical'):
        value = gauge.get(name)
        # JSON allows NaN and Infinity, and a max near 0 divides by zero in the log scale: either one would make
        # every push of the page fail in gauge_state.
        if name in gauge and (type(value) not in (int, float) or not math.isfinite(value)
                              or (name == 'max' and value < GAUGE_MIN_MAX)):
            raise ValueError(f'gauge.{name} must be a number' + (f' of at least {GAUGE_MIN_MAX}' if name == 'max' else ''))
    if gauge.get('fmt', 'int') not in GAUGE_FORMATS or gauge.get('scale', 'linear') not in ('linear', 'log'):
        raise ValueError('Invalid gauge format or scale')
    if not isinstance(gauge.get('unit', ''), str) or len(gauge.get('unit', '')) > 3:
        raise ValueError('gauge.unit must be at most 3 characters')
    if 'percent_key' in gauge and not isinstance(gauge['percent_key'], str):
        raise ValueError('gauge.percent_key must be text')
    if 'badge' in gauge and not (isinstance(gauge['badge'], str) and re.fullmatch(r'lc:[0-9a-f]{4}', gauge['badge'])):
        raise ValueError('gauge.badge must be a Lucide icon like lc:e186')


LIVE_KINDS = re.compile(r'media|timer:[A-Za-z0-9_.-]{1,64}|' + '|'.join(widgets.WIDGETS))


def _check_wide(button):
    """`span` makes a key 2-3 slots wide; `live` fills it with the music that plays or a timer's countdown."""
    span = button.get('span', 1)
    if type(span) is not int or not 1 <= span <= 3:
        raise ValueError('span must be 1, 2 or 3')
    live = button.get('live')
    if live is not None and (not isinstance(live, str) or not LIVE_KINDS.fullmatch(live) or span < 2):
        raise ValueError('live must be media, timer:NAME or a widget (' + ', '.join(widgets.WIDGETS) + '), on a key that is at least 2 slots wide')


def _check_button(button, pages, profiles):
    if not isinstance(button.get('label'), str) or not button['label'].strip():
        raise ValueError('The button needs a name')
    if not isinstance(button.get('icon', 'ok'), str) or len(button.get('icon', 'ok')) > 100:
        raise ValueError('Invalid button icon')
    _check_color(button.get('color', '#35D07F'), 'Invalid button color')
    for key in ('bg', 'text_color', 'border'):
        if key in button:
            _check_color(button[key], f'Invalid button {key.replace("_", " ")}')
    if 'gauge' in button:
        _check_gauge(button['gauge'])
    _check_wide(button)
    if 'status' in button:
        _check_status(button['status'])
    _check_actions(button.get('actions', []), pages, profiles)
    _check_actions(button.get('hold_actions', []), pages, profiles)
    _check_actions(button.get('double_actions', []), pages, profiles)
    if type(button.get('confirm', False)) is not bool:
        raise ValueError('confirm must be true or false')
    if button.get('confirm') and (button.get('hold_actions') or button.get('double_actions')):
        raise ValueError('A key that needs a hold to confirm cannot also have a long-press or double-press action')
    states = button.get('states', [])
    if not isinstance(states, list) or len(states) > 8 or (states and len(states) < 2):
        raise ValueError('A toggle button needs 2-8 states')
    for state in states:
        if not isinstance(state, dict):
            raise ValueError('Invalid button state')
        if not isinstance(state.get('label', ''), str) or not isinstance(state.get('icon', 'ok'), str):
            raise ValueError('Invalid state label or icon')
        _check_actions(state.get('actions', []), pages, profiles)
        _check_color(state.get('color', '#35D07F'), 'Invalid state color')
        for key in ('bg', 'text_color', 'border'):
            if key in state:
                _check_color(state[key], f'Invalid state {key.replace("_", " ")}')
    bind = button.get('bind')
    timer_bind = isinstance(bind, str) and bind.startswith('timer-running:') and LIVE_NAME.fullmatch(bind[14:])
    if 'bind' in button and ((bind not in FLAG_SOURCES and not timer_bind) or len(states) < 2):
        raise ValueError(f'bind must be one of {", ".join(FLAG_SOURCES)} or timer-running:NAME, and needs two states')
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
        try:
            _check_button(button, pages, profiles)
        except ValueError as exc:
            raise ValueError(f'{name}, key {bid}: {exc}') from exc
    for button in buttons:
        span, bid = button.get('span', 1), button['id']
        if span > 1 and ((bid - 1) % 6 + span > 6 or any(bid + extra in ids for extra in range(1, span))):
            raise ValueError(f'{name}: a key {span} slots wide at slot {bid} needs free slots to its right on the same row')


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
    target = spec.get('path' if kind == 'file' else 'name')
    if kind in ('file', 'variable') and (not isinstance(target, str) or not target.strip() or chr(0) in target):
        raise ValueError('Trigger is missing a path or variable name')
    _check_actions(trigger.get('actions', []), pages, profiles)


def _check_night(night):
    if (not isinstance(night, dict) or set(night) != {'from', 'to', 'brightness'}
            or not all(isinstance(night[key], str) and TIME_PATTERN.fullmatch(night[key]) for key in ('from', 'to'))
            or type(night['brightness']) is not int or not 1 <= night['brightness'] <= 100):
        raise ValueError('display.night needs from and to as HH:MM and a brightness from 1 to 100')


def in_quiet_hours(night, minute_of_day):
    """Whether the minute (0-1439) falls inside the night window, which may run past midnight."""
    if not night:
        return False
    start, end = (int(night[key][:2]) * 60 + int(night[key][3:]) for key in ('from', 'to'))
    if start == end:
        return False
    return start <= minute_of_day < end if start < end else minute_of_day >= start or minute_of_day < end


def _check_display(display):
    if not isinstance(display, dict):
        raise ValueError('display must be an object')
    limits = {'brightness': (1, 100), 'dim_after': (0, 86400), 'dim_level': (0, 100)}
    for key, value in display.items():
        if key == 'night':
            _check_night(value)
            continue
        if key not in limits:
            raise ValueError(f'Unknown display setting: {key}')
        low, high = limits[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'display.{key} must be a whole number from {low} to {high}')


def _check_panel(panel, pages=(), profiles=None):
    """The `panel` block: which agents, programs and readings the cockpit screens show."""
    import cockpit
    if not isinstance(panel, dict) or set(panel) - {'agents', 'apps', 'mic', 'stats', 'screens', 'shortcuts'}:
        raise ValueError('panel may only set agents, apps, mic, stats, screens and shortcuts')
    screens = panel.get('screens', list(cockpit.SCREENS))
    if not isinstance(screens, list) or len(set(screens)) != len(screens) or any(item not in cockpit.SCREENS for item in screens):
        raise ValueError('panel.screens must list keys, agents, mixer or status once each')
    shortcuts = panel.get('shortcuts', [])
    if not isinstance(shortcuts, list) or len(shortcuts) > cockpit.MAX_SHORTCUTS:
        raise ValueError(f'panel.shortcuts holds at most {cockpit.MAX_SHORTCUTS} shortcuts')
    for shortcut in shortcuts:
        if isinstance(shortcut, dict) and shortcut.get('type') == 'actions':
            # a shortcut that runs steps, like a key, instead of opening a page
            if (set(shortcut) - {'type', 'actions', 'label', 'icon'} or not isinstance(shortcut.get('label', ''), str)
                    or len(shortcut.get('label', '')) > 40 or not re.fullmatch(r'lc:[0-9a-f]{4}', shortcut.get('icon', 'lc:e0ff'))
                    or not isinstance(shortcut.get('actions'), list) or not shortcut['actions']):
                raise ValueError('an action shortcut needs its steps, an icon like lc:e0ff and a name of at most 40 characters')
            _check_actions(shortcut['actions'], pages, profiles or {})
        elif (not isinstance(shortcut, dict) or set(shortcut) - {'profile', 'page', 'icon', 'type'} or shortcut.get('type', 'page') != 'page'
                or any(not isinstance(shortcut.get(key), str) or not 0 < len(shortcut[key]) <= 100 for key in ('profile', 'page'))
                or not re.fullmatch(r'lc:[0-9a-f]{4}', shortcut.get('icon', 'lc:e0ff'))):
            raise ValueError('a shortcut needs a profile, a page and an icon like lc:e0ff')
    agents = panel.get('agents', [])
    if not isinstance(agents, list) or any(item not in [key for key, _, _ in cockpit.AGENTS] for item in agents):
        raise ValueError('panel.agents must list claude, codex or zcode')
    apps = panel.get('apps', [])
    if (not isinstance(apps, list) or len(apps) > cockpit.MAX_APPS
            or any(not isinstance(item, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,35}\.exe', item) for item in apps)):
        raise ValueError(f'panel.apps must list at most {cockpit.MAX_APPS} program names ending in .exe')
    if type(panel.get('mic', True)) is not bool:
        raise ValueError('panel.mic must be true or false')
    stats = panel.get('stats', [])
    if not isinstance(stats, list) or any(item not in cockpit.STAT_IDS for item in stats):
        raise ValueError('panel.stats must list readings the panel knows')


def _validate_config(config):
    profiles = config.get('profiles') if isinstance(config, dict) else None
    if isinstance(config, dict) and version_of(config) > CONFIG_VERSION:
        raise ValueError('This configuration was saved by a newer Tessera; update Tessera to use it')
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
    if 'ambient' in config:
        check_ambient(config['ambient'])
    if 'calendar' in config:
        calendar_feed.check_settings(config['calendar'])
    theme = config.get('theme', {})
    if not isinstance(theme, dict) or set(theme) - {'bg', 'text_color', 'border'}:
        raise ValueError('theme may only set bg, text_color and border')
    for key, value in theme.items():
        _check_color(value, f'Invalid theme {key.replace("_", " ")}')
    if 'panel' in config:
        _check_panel(config['panel'], {page for profile in profiles.values() for page in profile['pages']}, profiles)
    if 'plugins' in config:
        check_plugin_config(config['plugins'])
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
