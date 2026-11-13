"""Inspect a profile bundle before it is imported: which actions run commands, call the network or run by themselves."""
from __future__ import annotations

import copy
import re

SENSITIVE_HEADERS = ('authorization', 'proxy-authorization', 'x-api-key', 'api-key', 'x-auth-token', 'cookie')
DOCUMENT_SUFFIXES = ('.txt', '.pdf', '.md')
WEB_TARGET = re.compile(r'(?i)^(https?://|mailto:|ms-settings:|steam://|spotify:|discord://)')
# A plugin command controls an outside system (a smart home, a stream), so it counts like a web request.
EXECUTABLE_KINDS = ('shell', 'http', 'plugin')
SECRET_SETTING = re.compile(r'(?i)token|secret|password|api.?key')
MAX_LISTED = 200


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
        detail = f"{action.get('method', 'GET')} {str(action.get('url', ''))[:160]}"
        if action.get('body'):
            detail += ' with a request body'
        return 'medium', 'calls ' + detail
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
    """A copy without shell, HTTP and plugin actions, program launches that are not web links, automatic rules and plugin setup."""
    safe = copy.deepcopy(config)
    for _, owner, key, _ in list(iter_actions(safe)):
        owner[key] = [action for action in owner[key]
                      if not (isinstance(action, dict)
                              and (action.get('type') in EXECUTABLE_KINDS
                                   or (action.get('type') == 'open' and _classify(action))))]
    safe['triggers'] = []
    # Plugin setup turns code on; the editor keeps the plugins already set up on this PC instead.
    safe.pop('plugins', None)
    panel = safe.get('panel')
    if isinstance(panel, dict) and isinstance(panel.get('shortcuts'), list):  # a step shortcut left without steps is refused
        panel['shortcuts'] = [item for item in panel['shortcuts'] if not (isinstance(item, dict) and item.get('type') == 'actions' and not item.get('actions'))]
    return safe


def env_name(header: str) -> str:
    return 'TESSERA_' + re.sub(r'[^A-Z0-9]+', '_', header.upper()).strip('_')


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
    names = []
    for _, owner, key, _ in iter_actions(shared):
        for action in owner[key]:
            headers = action.get('headers') if isinstance(action, dict) and action.get('type') == 'http' else None
            for header in list(headers or {}):
                if header.lower() in SENSITIVE_HEADERS and not headers[header].startswith('$(env:'):
                    headers[header] = f'$(env:{env_name(header)})'
                    names.append(env_name(header))
    return shared, sorted(set(names))
