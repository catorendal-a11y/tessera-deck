"""Dry run of a button: explain in plain words what pressing it would do, without doing any of it."""
from __future__ import annotations

import os
import urllib.parse

from program_locator import locate
from substitution import ENV_REFERENCE, substitute

MAX_TEXT = 90


def _clip(text: str) -> str:
    text = text.replace('\r', ' ').replace('\n', ' ')
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + '…'


def _step(action: dict, variables: dict[str, str], environment, locator) -> tuple[bool, str]:
    from tesserad import parse_hotkey  # imported late: tesserad is heavy
    kind = action.get('type')
    if kind == 'hotkey':
        try:
            parse_hotkey(action['keys'])
        except (ValueError, KeyError) as exc:
            return False, f'Unknown key combination: {exc}'
        return True, f'Press {action["keys"]}'
    if kind == 'text':
        slow = f' at {action["delay_ms"]} ms per character' if action.get('delay_ms') else ''
        return True, f'Type "{_clip(substitute(action["text"], variables))}"{slow}'
    if kind == 'open':
        target = os.path.expandvars(substitute(action['target'], variables))
        if '://' in target or target.lower().startswith(('mailto:', 'ms-settings:', 'shell:')):
            return True, f'Open {_clip(target)}'
        found = target if os.path.exists(target) else locator(target)
        if found is None:
            return False, f'Open {_clip(target)}: the program or file was not found on this PC'
        return True, f'Open {_clip(found)}' + ('' if found == target else ' (found in a different place)')
    if kind == 'shell':
        try:
            command = substitute(action['command'], variables, 'shell')
        except ValueError as exc:
            return False, str(exc)
        return True, f'Run the command: {_clip(command)} (timeout {action.get("timeout", 30)} s)'
    if kind == 'http':
        url = substitute(action['url'], variables, 'url')
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            return False, f'Request {_clip(url)}: the address must start with http:// or https://'
        names = sorted({name for part in (*action.get('headers', {}).values(), action.get('body', ''))
                        for name in ENV_REFERENCE.findall(part)})
        known = os.environ if environment is None else environment
        missing = [name for name in names if name not in known]
        text = f'Send {action.get("method", "GET")} {_clip(url)}'
        if missing:
            return False, text + f': the environment variable {", ".join(missing)} is not set'
        return True, text + (f' using {", ".join(names)} from the environment' if names else '')
    if kind == 'delay':
        return True, f'Wait {action.get("ms", 100) / 1000:g} s'
    if kind in ('page', 'folder'):
        return True, f'{"Open folder" if kind == "folder" else "Go to page"} "{action["page"]}"'
    if kind == 'profile':
        return True, f'Switch to profile "{action["profile"]}"'
    if kind == 'back':
        return True, 'Go back one level'
    if kind == 'home':
        return True, 'Go to the first page of the default profile'
    if kind == 'press':
        return True, f'Press key {action["id"]}'
    if kind == 'state':
        return True, f'Set the state of key {action["button"]} to {action.get("state", "next")}'
    if kind == 'set':
        value = _clip(substitute(str(action.get('value', '')), variables))
        return True, f'Set variable {action["variable"]} to "{value}"'
    if kind == 'audio':
        op, target = action.get('op', 'toggle'), action['target']
        who = target.removeprefix('app:') + ' (its own sound)' if target.startswith('app:') else f'the {target}'
        if op == 'volume':
            return True, f'Set the volume of {who} to {action.get("value")}%'
        if op in ('up', 'down'):
            return True, f'Turn the volume of {who} {op} by {action.get("step", 5)}%'
        return True, f'{op.capitalize()} {who}'
    if kind == 'counter':
        op, step, value = action.get('op', 'inc'), action.get('step', 1), action.get('value', 0)
        detail = {'inc': f'add {step} to', 'dec': f'subtract {step} from', 'set': f'set to {value}:',
                  'reset': f'reset to {value}:'}[op]
        return True, f'Counter: {detail} {action["name"]}'
    if kind == 'timer':
        seconds = f' for {action["seconds"]} s' if action.get('seconds') else ''
        notify = f', notify "{_clip(action["notify"])}"' if action.get('notify') else ''
        return True, f'Timer {action["name"]}: {action.get("op", "toggle")}{seconds}{notify}'
    return False, f'Unknown action type {kind!r}'


def preview(actions: list[dict], variables: dict[str, str], environment=None, locator=locate) -> dict:
    """What `actions` would do, step by step, using the panel's current variable values."""
    steps, waited = [], 0.0
    for index, action in enumerate(actions, 1):
        try:
            ok, text = _step(action, variables, environment, locator)
        except (ValueError, KeyError, TypeError) as exc:
            ok, text = False, f'Cannot run this step: {exc}'
        if isinstance(action, dict) and action.get('type') == 'delay':
            waited += action.get('ms', 100) / 1000
        steps.append({'index': index, 'type': action.get('type') if isinstance(action, dict) else None,
                      'ok': ok, 'text': text})
    return {'ok': all(step['ok'] for step in steps), 'steps': steps, 'wait_seconds': round(waited, 3),
            'executed': False}
