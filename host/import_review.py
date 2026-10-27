"""Inspect a profile bundle before it is imported: which actions run commands, call the network or run by themselves."""
from __future__ import annotations

import copy
import re

SENSITIVE_HEADERS = ('authorization', 'proxy-authorization', 'x-api-key', 'api-key', 'x-auth-token', 'cookie')
DOCUMENT_SUFFIXES = ('.txt', '.pdf', '.md')
WEB_TARGET = re.compile(r'(?i)^(https?://|mailto:|ms-settings:|steam://|spotify:|discord://)')
EXECUTABLE_KINDS = ('shell', 'http')
MAX_LISTED = 200


def _button_lists(config):
    for profile_name, profile in config.get('profiles', {}).items():
        for page_name, buttons in profile.get('pages', {}).items():
            yield f"Profile '{profile_name}' / page '{page_name}'", buttons
        yield f"Profile '{profile_name}' / pinned", profile.get('pinned', [])


def iter_actions(config):
    """Yield (location, owner, key, automatic) for every action list in the configuration."""
    for where, buttons in _button_lists(config):
        for button in buttons:
            name = f"{where} / button {button.get('id')} '{button.get('label', '')}'"
            for key, suffix in (('actions', ''), ('hold_actions', ' (long press)'), ('double_actions', ' (double press)')):
                if isinstance(button.get(key), list):
                    yield name + suffix, button, key, False
            for number, state in enumerate(button.get('states', []), 1):
                if isinstance(state.get('actions'), list):
                    yield f'{name} state {number}', state, 'actions', False
    for number, trigger in enumerate(config.get('triggers', []), 1):
        if isinstance(trigger.get('actions'), list):
            yield f'Automatic rule {number} ({trigger.get("when", {}).get("type", "?")})', trigger, 'actions', True


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
    if kind == 'open':
        target = str(action.get('target', ''))
        if WEB_TARGET.match(target) or target.lower().endswith(DOCUMENT_SUFFIXES):
            return None
        return 'medium', f'launches: {target[:160]}'
    return None


def review(config: dict) -> list[dict]:
    """Findings for everything in the configuration that executes code, reaches the network or runs by itself."""
    findings = []
    for where, owner, key, automatic in iter_actions(config):
        for action in owner[key]:
            if not isinstance(action, dict):
                continue
            found = _classify(action)
            if found is None and automatic and action.get('type') in ('hotkey', 'text'):
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
    """A copy without shell and HTTP actions, program launches that are not web links, and automatic rules."""
    safe = copy.deepcopy(config)
    for _, owner, key, _ in list(iter_actions(safe)):
        owner[key] = [action for action in owner[key]
                      if not (isinstance(action, dict)
                              and (action.get('type') in EXECUTABLE_KINDS
                                   or (action.get('type') == 'open' and _classify(action))))]
    safe['triggers'] = []
    return safe


def env_name(header: str) -> str:
    return 'TESSERA_' + re.sub(r'[^A-Z0-9]+', '_', header.upper()).strip('_')


def redact_secrets(config: dict) -> tuple[dict, list[str]]:
    """A copy for export: credentials in HTTP headers become $(env:NAME) references. Returns it and the names used."""
    shared = copy.deepcopy(config)
    names = []
    for _, owner, key, _ in iter_actions(shared):
        for action in owner[key]:
            headers = action.get('headers') if isinstance(action, dict) and action.get('type') == 'http' else None
            for header in list(headers or {}):
                if header.lower() in SENSITIVE_HEADERS and not headers[header].startswith('$(env:'):
                    headers[header] = f'$(env:{env_name(header)})'
                    names.append(env_name(header))
    return shared, sorted(set(names))
