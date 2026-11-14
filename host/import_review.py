"""Inspect a profile bundle before it is imported: which actions run commands, call the network or run by themselves."""
from __future__ import annotations

import copy
import re
import urllib.parse

from ha_keys import SECRET_DATA

SENSITIVE_HEADERS = ('authorization', 'proxy-authorization', 'x-api-key', 'api-key', 'x-auth-token', 'cookie')
DOCUMENT_SUFFIXES = ('.txt', '.pdf', '.md')
WEB_TARGET = re.compile(r'(?i)^(https?://|mailto:|ms-settings:|steam://|spotify:|discord://)')
# A plugin command controls an outside system (a smart home, a stream), so it counts like a web request, and so does
# a Home Assistant action, which the panel sends over the network to the smart home.
EXECUTABLE_KINDS = ('shell', 'http', 'plugin', 'homeassistant')
SECRET_SETTING = re.compile(r'(?i)token|secret|password|api.?key')
MAX_LISTED = 200
TYPED = ('text', 'clipboard')  # after a hotkey (Win+R, a terminal) typed text is a command
# Home Assistant domains whose actions open doors, disarm alarms or run anything: the panel runs them with the PC off
HA_HIGH_DOMAINS = {'lock': 'can unlock a door', 'alarm_control_panel': 'can disarm an alarm',
                   'cover': 'can open a garage door or gate', 'script': 'runs a Home Assistant script',
                   'automation': 'runs or changes a Home Assistant automation', 'shell_command': 'runs a command in Home Assistant',
                   'rest_command': 'sends a web request from Home Assistant', 'homeassistant': 'can restart or change Home Assistant',
                   'button': 'presses a device button', 'input_button': 'presses a Home Assistant button'}


def _typed_after_hotkey(actions) -> bool:
    """A hotkey and typed text in one list: Win+R, a command and Enter runs it, though no step is a command."""
    kinds = {action.get('type') for action in actions if isinstance(action, dict)}
    return 'hotkey' in kinds and bool(kinds & set(TYPED))


def _button_lists(config):
    for profile_name, profile in config.get('profiles', {}).items():
        for page_name, buttons in profile.get('pages', {}).items():
            yield f"Profile '{profile_name}' / page '{page_name}'", buttons
        yield f"Profile '{profile_name}' / pinned", profile.get('pinned', [])


def _with_timers(where, owner, key, automatic):
    """The list itself, then the actions a timer in it runs when it ends (a timer can hold a shell command too)."""
    yield where, owner, key, automatic
    for action in owner[key]:
        if isinstance(action, dict) and action.get('type') == 'timer' and isinstance(action.get('actions'), list):
            yield from _with_timers(f"{where} when timer '{action.get('name', '')}' ends", action, 'actions', automatic)


def iter_actions(config):
    """Yield (location, owner, key, automatic) for every action list in the configuration."""
    for where, buttons in _button_lists(config):
        for button in buttons:
            name = f"{where} / button {button.get('id')} '{button.get('label', '')}'"
            for key, suffix in (('actions', ''), ('hold_actions', ' (long press)'), ('double_actions', ' (double press)')):
                if isinstance(button.get(key), list):
                    yield from _with_timers(name + suffix, button, key, False)
            for number, state in enumerate(button.get('states', []), 1):
                if isinstance(state.get('actions'), list):
                    yield from _with_timers(f'{name} state {number}', state, 'actions', False)
    for number, shortcut in enumerate((config.get('panel') or {}).get('shortcuts') or [], 1):
        if isinstance(shortcut, dict) and isinstance(shortcut.get('actions'), list):
            yield from _with_timers(f"Rail shortcut {number} '{shortcut.get('label', '')}'", shortcut, 'actions', False)
    for number, trigger in enumerate(config.get('triggers', []), 1):
        if isinstance(trigger.get('actions'), list):
            yield from _with_timers(f'Automatic rule {number} ({trigger.get("when", {}).get("type", "?")})', trigger, 'actions', True)


def _classify(action):
    """Return (risk, detail) for an action worth showing to the user, or None."""
    kind = action.get('type')
    if kind == 'shell':
        return 'high', f"runs the command: {str(action.get('command', ''))[:160]}"
    if kind == 'http':
        url = str(action.get('url', ''))
        detail = f"{action.get('method', 'GET')} {url[:160]}"
        try:  # the host decides who receives the request; a long address could hide it past the cut
            host = urllib.parse.urlsplit(url).hostname
        except ValueError:
            host = None
        detail += f' (host {host})' if host and '$(' not in host else ' (host set when it runs)'
        if action.get('body'):
            detail += ' with a request body'
        return 'medium', 'calls ' + detail
    if kind == 'homeassistant':
        name, entity = str(action.get('action', ''))[:64], str(action.get('entity_id', ''))[:128]
        data = action.get('data') if isinstance(action.get('data'), dict) else {}
        detail = (f'the panel calls Home Assistant {name}' + (f' on {entity}' if entity else '')
                  + (f" with {', '.join(str(key)[:32] for key in data)}" if data else '') + ' over the network, also with the PC off')
        warning = HA_HIGH_DOMAINS.get(name.split('.')[0])
        return ('high', f'{warning}: {detail}') if warning else ('medium', detail)
    if kind == 'plugin':
        return 'medium', f"runs plugin {str(action.get('plugin', ''))[:60]}.{str(action.get('command', ''))[:60]}"
    if kind == 'open':
        target = str(action.get('target', ''))
        if WEB_TARGET.match(target) or target.lower().endswith(DOCUMENT_SUFFIXES):
            return None
        return 'medium', f'launches: {target[:160]}'
    return None


def review(config: dict) -> list[dict]:
    """Findings for everything in the configuration that executes code, reaches the network or runs by itself."""
    findings = []
    # The file can switch installed plugins on and point them somewhere else (a new server address).
    for plugin_id, entry in (config.get('plugins') or {}).items():
        if isinstance(entry, dict) and entry.get('enabled'):
            settings = ', '.join(str(name)[:40] for name in (entry.get('settings') or {}))
            findings.append({'where': 'Plugins', 'kind': 'plugins', 'risk': 'medium', 'automatic': False,
                             'detail': f'turns on plugin {str(plugin_id)[:60]}' + (f' with settings: {settings[:160]}' if settings else '')})
    for where, owner, key, automatic in iter_actions(config):
        if _typed_after_hotkey(owner[key]):
            findings.append({'where': where, 'kind': 'hotkey', 'risk': 'high' if automatic else 'medium', 'automatic': automatic,
                             'detail': 'presses a hotkey and types text, which can run a command (for example Win+R)'})
        for action in owner[key]:
            if not isinstance(action, dict):
                continue
            found = _classify(action)
            if found is None and automatic and action.get('type') in ('hotkey', 'text', 'clipboard', 'window'):
                found = ('medium', f"{action['type']} is sent automatically")
            if found is None:
                continue
            risk, detail = found
            if automatic and action.get('type') in EXECUTABLE_KINDS:
                risk = 'high'
            findings.append({'where': where, 'kind': action.get('type'), 'risk': risk, 'detail': detail,
                             'automatic': automatic})
            if len(findings) >= MAX_LISTED:
                return findings
    return findings


def strip_executable(config: dict) -> dict:
    """A copy without shell, HTTP and plugin actions, program launches that are not web links, text typed after a
    hotkey, automatic rules and plugin setup."""
    safe = copy.deepcopy(config)
    for _, owner, key, _ in list(iter_actions(safe)):
        typed = _typed_after_hotkey(owner[key])
        owner[key] = [action for action in owner[key]
                      if not (isinstance(action, dict)
                              and (action.get('type') in EXECUTABLE_KINDS
                                   or (typed and action.get('type') in TYPED)
                                   or (action.get('type') == 'open' and _classify(action))))]
    safe['triggers'] = []
    # Plugin setup turns code on; the editor keeps the plugins already set up on this PC instead.
    safe.pop('plugins', None)
    panel = safe.get('panel')
    if isinstance(panel, dict) and isinstance(panel.get('shortcuts'), list):  # a step shortcut left without steps is refused
        panel['shortcuts'] = [item for item in panel['shortcuts'] if not (isinstance(item, dict) and item.get('type') == 'actions' and not item.get('actions'))]
    return safe


def _ha_secrets(config):
    """(action, data name) for Home Assistant data values named like a code or password (ha_keys.SECRET_DATA)."""
    for _, owner, key, _ in iter_actions(config):
        for action in owner[key]:
            data = action.get('data') if isinstance(action, dict) and action.get('type') == 'homeassistant' else None
            if isinstance(data, dict):
                yield from ((action, name) for name in data if isinstance(name, str) and SECRET_DATA.search(name))


def _ha_secret_names(config):
    return (name for _, name in _ha_secrets(config))


def env_name(header: str) -> str:
    return 'TESSERA_' + re.sub(r'[^A-Z0-9]+', '_', header.upper()).strip('_')


def export_left_out(config: dict) -> list[str]:
    """What redact_secrets drops, in plain words, so the editor can say so after an export."""
    out = ['the calendar address'] if 'calendar' in config else []
    out += [f'Home Assistant data {name}' for name in sorted(set(_ha_secret_names(config)))]
    for name, plugin in sorted((config.get('plugins') or {}).items()):
        settings = plugin.get('settings') if isinstance(plugin, dict) else None
        out += [f'plugin {name}: {key}' for key in (settings or {}) if SECRET_SETTING.search(key)]
    return out


def redact_secrets(config: dict) -> tuple[dict, list[str]]:
    """A copy for export: credentials in HTTP headers become $(env:NAME) references. Returns it and the names used.

    The calendar's iCal address and plugin settings named like a secret (a token or a password) are left out:
    anyone with them can read the calendar or act as the plugin's account.
    """
    shared = copy.deepcopy(config)
    shared.pop('calendar', None)
    for plugin in (shared.get('plugins') or {}).values():
        settings = plugin.get('settings') if isinstance(plugin, dict) else None
        for name in list(settings or {}):
            if SECRET_SETTING.search(name):
                del settings[name]
    for action, name in list(_ha_secrets(shared)):
        del action['data'][name]
        if not action['data']:
            del action['data']
    names = []
    for _, owner, key, _ in iter_actions(shared):
        for action in owner[key]:
            headers = action.get('headers') if isinstance(action, dict) and action.get('type') == 'http' else None
            for header in list(headers or {}):
                if header.lower() in SENSITIVE_HEADERS and not headers[header].startswith('$(env:'):
                    headers[header] = f'$(env:{env_name(header)})'
                    names.append(env_name(header))
    return shared, sorted(set(names))
