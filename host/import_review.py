"""Inspect a profile bundle before it is imported: which actions run commands, call the network or run by themselves."""
from __future__ import annotations

import copy
import re
import urllib.parse

from program_name import SUFFIX
from substitution import ENV_REFERENCE

# Header and address field names that carry a credential: Authorization, Private-Token, X-Api-Key, ?key=, ?sig=
SECRET_FIELD = re.compile(r'(?i)auth(?!ors?\b)|token|secret|passw(?:or)?d|api.?key|(?:^|[-_])key$|^sig$|signature'
                          r'|cookie|session|credential')
QUERY_FIELD = re.compile(r'([?&])([^=&#]+)=([^&#]*)')
DOCUMENT_SUFFIXES = ('.txt', '.pdf', '.md')
WEB_TARGET = re.compile(r'(?i)^(https?://|mailto:|ms-settings:|steam://|spotify:|discord://)')
# A plugin command controls an outside system (a smart home, a stream), so it counts like a web request. So does a
# Home Assistant step: this version skips it, and the Wi-Fi beta's panel sends it to the smart home.
EXECUTABLE_KINDS = ('shell', 'script', 'http', 'plugin', 'homeassistant')
SECRET_SETTING = re.compile(r'(?i)token|secret|password|api.?key')
MAX_LISTED = 200
# The data of a Home Assistant step (kept from the Wi-Fi beta) named like a code or a password, such as an alarm code
HA_SECRET_DATA = re.compile(r'(?i)(^|_)(code|pin|password|passcode|passwd|token|secret)($|_)')
TYPED = ('text', 'clipboard')  # after a hotkey (Win+R, a terminal) typed text is a command


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
    if kind == 'script':
        return 'high', f"runs the script: {str(action.get('path', ''))[:160]}"
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
        headers = action.get('headers') if isinstance(action.get('headers'), dict) else {}
        text = ' '.join(str(part) for pair in headers.items() for part in pair) + f" {url} {action.get('body') or ''}"
        names = list(dict.fromkeys(ENV_REFERENCE.findall(text)))
        if names:  # a secret from this PC's environment leaves in the request
            return 'high', 'calls ' + detail + ' and sends ' + ', '.join(f'$(env:{name})' for name in names)
        return 'medium', 'calls ' + detail
    if kind == 'plugin':
        return 'medium', f"runs plugin {str(action.get('plugin', ''))[:60]}.{str(action.get('command', ''))[:60]}"
    if kind == 'homeassistant':
        return 'medium', f"calls Home Assistant {str(action.get('action', ''))[:64]} when the file runs on the Wi-Fi beta"
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
    if len(findings) > MAX_LISTED:  # the user may keep all of them: the worst come first, and the cut is said
        findings.sort(key=lambda finding: finding['risk'] != 'high')
        more = len(findings) - MAX_LISTED
        findings[MAX_LISTED:] = [{'where': 'The file', 'kind': 'more', 'risk': 'high', 'automatic': False,
                                  'detail': f'has {more} more actions like these that are not listed'}]
    return findings


def adapt_to_this_system(config: dict):
    """A copy that this PC accepts, and where it changed. A file made on the other system holds script paths and program
    names that are wrong here: the script steps this system cannot run are dropped, and a program name gets the .exe
    Windows needs. validate_config stays strict, so without this the import is refused before the user can choose."""
    from config_check import _check_script  # here, not at the top: config_check reaches this module through secrets_store
    from pc_state import APP_TARGET
    adapted, where, emptied = copy.deepcopy(config), [], []
    for place, owner, key, _ in list(iter_actions(adapted)):
        kept = []
        for action in owner[key]:
            if isinstance(action, dict) and action.get('type') == 'script':
                try:
                    _check_script(action, None, None)
                except ValueError as exc:
                    if str(exc).startswith('script:'):
                        where.append(place)
                        continue
            target = action.get('target') if isinstance(action, dict) and action.get('type') == 'audio' else None
            if isinstance(target, str) and not APP_TARGET.fullmatch(target) and APP_TARGET.fullmatch(target + '.exe'):
                action['target'] = target + '.exe'
                where.append(place)
            kept.append(action)
        if owner[key] and not kept:
            emptied.append(owner)
        owner[key] = kept
    panel = adapted.get('panel')
    if isinstance(panel, dict) and isinstance(panel.get('shortcuts'), list):  # a rail shortcut needs a step; a key may be empty
        panel['shortcuts'] = [item for item in panel['shortcuts'] if not any(item is gone for gone in emptied)]
    apps =panel.get('apps') if isinstance(panel, dict) else None
    if isinstance(apps, list):
        fixed = [f'{app}.exe' if isinstance(app, str) and not re.fullmatch(rf'[A-Za-z0-9_.-]{{1,35}}{SUFFIX}', app)
                 and re.fullmatch(rf'[A-Za-z0-9_.-]{{1,35}}{SUFFIX}', app + '.exe') else app for app in apps]
        if fixed != apps:
            panel['apps'] = fixed
            where.append('panel apps')
    return adapted, list(dict.fromkeys(where))


def strip_executable(config: dict) -> dict:
    """A copy without shell, HTTP, plugin and Home Assistant actions, program launches that are not web links, text
    typed after a hotkey, automatic rules and plugin setup."""
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
    """(step, data name) for each Home Assistant data value named like a code or a password."""
    for _, owner, key, _ in iter_actions(config):
        for action in owner[key]:
            data = action.get('data') if isinstance(action, dict) and action.get('type') == 'homeassistant' else None
            if isinstance(data, dict):
                yield from ((action, name) for name in data if isinstance(name, str) and HA_SECRET_DATA.search(name))


def env_name(header: str) -> str:
    return 'TESSERA_' + re.sub(r'[^A-Z0-9]+', '_', header.upper()).strip('_')


def export_left_out(config: dict) -> list[str]:
    """What redact_secrets drops, in plain words, so the editor can say so after an export."""
    out = ['the calendar address'] if 'calendar' in config else []
    out += [f'Home Assistant data {name}' for name in sorted({name for _, name in _ha_secrets(config)})]
    for name, plugin in sorted((config.get('plugins') or {}).items()):
        settings = plugin.get('settings') if isinstance(plugin, dict) else None
        out += [f'plugin {name}: {key}' for key in (settings or {}) if SECRET_SETTING.search(key)]
    return out


def redact_secrets(config: dict) -> tuple[dict, list[str]]:
    """A copy for export: credentials in HTTP headers and in address fields (?token=) become $(env:NAME) references.
    Returns it and the names used.

    The calendar's iCal address and plugin settings named like a secret (a token or a password) are left out:
    anyone with them can read the calendar or act as the plugin's account. So is a code or password in the data of a
    Home Assistant step.
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
    names = []

    def hide_field(match):
        lead, field, value = match.groups()
        name = urllib.parse.unquote(field)
        if not SECRET_FIELD.search(name) or value.startswith('$(env:'):
            return match.group(0)
        names.append(env_name(name))
        return f'{lead}{field}=$(env:{env_name(name)})'

    for _, owner, key, _ in iter_actions(shared):
        for action in owner[key]:
            if not (isinstance(action, dict) and action.get('type') == 'http'):
                continue
            headers = action.get('headers')
            for header in list(headers or {}):
                if SECRET_FIELD.search(header) and not headers[header].startswith('$(env:'):
                    headers[header] = f'$(env:{env_name(header)})'
                    names.append(env_name(header))
            if isinstance(action.get('url'), str):
                action['url'] = QUERY_FIELD.sub(hide_field, action['url'])
    return shared, sorted(set(names))
