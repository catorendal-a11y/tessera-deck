"""Dry run of a button: explain in plain words what pressing it would do, without doing any of it."""
from __future__ import annotations

import os
import re
import shutil

from action_runner import script_path
from desktop import locate, script_command
from input_common import split_hotkey
from substitution import ENV_REFERENCE, check_web_url, expand_environment, substitute


MAX_TEXT = 90
URI_SCHEME = re.compile(r'(?i)[a-z][a-z0-9+.-]+:')  # two or more letters, so a drive letter is not a scheme


def _clip(text: str) -> str:
    text = text.replace('\r', ' ').replace('\n', ' ')
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + '…'


def toggled(action: dict, current) -> str:
    """The value a toggle action sets: the second value after the first, else the first (also when unset)."""
    first, second = action.get('values', ['on', 'off'])
    return second if current == first else first


WINDOW_WORDS = {'minimize': 'Minimize', 'maximize': 'Maximize', 'restore': 'Restore', 'close': 'Close',
                'topmost': 'Toggle always on top for', 'next_monitor': 'Move to the next monitor:', 'focus': 'Bring to the front'}


def _step(action: dict, variables: dict[str, str], environment, locator) -> tuple[bool, str]:
    kind = action.get('type')
    if kind == 'hotkey':
        try:
            split_hotkey(action['keys'])
        except (ValueError, KeyError) as exc:
            return False, f'Unknown key combination: {exc}'
        return True, f'Press {action["keys"]}'
    if kind == 'text':
        slow = f' at {action["delay_ms"]} ms per character' if action.get('delay_ms') else ''
        return True, f'Type "{_clip(substitute(action["text"], variables))}"{slow}'
    if kind == 'open':
        target = substitute(action['target'], variables)
        if URI_SCHEME.match(target):
            return True, f'Open {_clip(target)}'
        target = os.path.expandvars(target)
        # os.startfile also finds a bare name (notepad, mmsys.cpl, code) through PATH and App Paths (winword)
        found = target if os.path.exists(target) or shutil.which(target, mode=os.F_OK) else locator(target)
        if found is None and not os.path.splitext(target)[1]:
            found = locator(target + '.exe')
        if found is None:
            return False, f'Open {_clip(target)}: the program or file was not found on this PC'
        return True, f'Open {_clip(found)}' + ('' if found == target else ' (found in a different place)')
    if kind == 'shell':
        try:
            command = substitute(action['command'], variables, 'shell')
        except ValueError as exc:
            return False, str(exc)
        return True, f'Run the command: {_clip(command)} (timeout {action.get("timeout", 30)} s)'
    if kind == 'script':
        try:
            path = script_path(action['path'])
        except ValueError as exc:
            return False, f'Run the script {_clip(action["path"])}: {_clip(str(exc))}'
        try:
            command = script_command(path)
            program = 'cmd' if isinstance(command, str) else os.path.basename(command[0])
        except ValueError as exc:
            return False, f'Run the script {_clip(path)}: {exc}'
        return True, f'Run the script {_clip(path)} with {program} (timeout {action.get("timeout", 30)} s)'
    if kind == 'http':
        url = substitute(action['url'], variables, 'url')
        names = sorted({name for part in (url, *action.get('headers', {}).values(), action.get('body', ''))
                        for name in ENV_REFERENCE.findall(part)})
        known = os.environ if environment is None else environment
        missing = [name for name in names if name not in known]
        text = f'Send {action.get("method", "GET")} {_clip(url)}'
        if missing:
            return False, text + f': the environment variable {", ".join(missing)} is not set'
        try:
            check_web_url(expand_environment(url, known))
        except ValueError as exc:
            return False, f'Request {_clip(url)}: {str(exc).lower()}'
        return True, text + (f' using {", ".join(names)} from the environment' if names else '')
    if kind == 'delay':
        return True, f'Wait {action.get("ms", 100) / 1000:g} s'
    if kind in ('page', 'folder'):
        return True, f'{"Open folder" if kind == "folder" else "Go to page"} "{action["page"]}"'
    if kind == 'profile':
        return True, f'Switch to profile "{action["profile"]}"' + (f', page "{action["page"]}"' if action.get('page') else '')
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
    if kind == 'screen':
        words = {'clock': 'Show the clock screen on the panel', 'keys': 'Show the keys on the panel',
                 'toggle': 'Switch the panel between the clock and the keys'}
        return True, words[action['show']]
    if kind == 'audio':
        op, target = action.get('op', 'toggle'), action['target']
        who = target.removeprefix('app:') + ' (its own sound)' if target.startswith('app:') else f'the {target}'
        if op == 'volume':
            return True, f'Set the volume of {who} to {action.get("value")}%'
        if op in ('up', 'down'):
            return True, f'Turn the volume of {who} {op} by {action.get("step", 5)}%'
        return True, f'{op.capitalize()} {who}'
    if kind == 'media':
        return True, 'Toggle shuffle in the media player' if action['op'] == 'shuffle' else 'Cycle repeat in the media player'
    if kind == 'remote_media':
        device = action.get('device', 'first')
        who = 'the first paired device that is reachable' if device == 'first' else 'a paired device'
        words = {'playpause': 'Play or pause', 'play': 'Play', 'pause': 'Pause', 'next': 'Skip to the next track', 'previous': 'Go back to the previous track', 'stop': 'Stop'}
        if action['op'] in ('volumeup', 'volumedown'):
            return True, f'Turn the volume of {who} {action["op"][6:]} by {action.get("step", 5)}% (KDE Connect)'
        return True, f'{words[action["op"]]} on {who} (KDE Connect)'
    if kind == 'mouse':
        op = action['op']
        words = {'left': 'Click the left mouse button', 'right': 'Click the right mouse button',
                 'middle': 'Click the middle mouse button', 'double': 'Double-click the left mouse button',
                 'scroll': f'Scroll {abs(action.get("amount", 0))} notch(es) {"up" if action.get("amount", 0) >= 0 else "down"}',
                 'move': f'Move the pointer by {action.get("x", 0)}, {action.get("y", 0)} pixels',
                 'moveto': f'Move the pointer to {action.get("x")}, {action.get("y")} on the screen'}
        return True, words[op]
    if kind == 'counter':
        op, step, value = action.get('op', 'inc'), action.get('step', 1), action.get('value', 0)
        detail = {'inc': f'add {step} to', 'dec': f'subtract {step} from', 'set': f'set to {value}:',
                  'reset': f'reset to {value}:'}[op]
        return True, f'Counter: {detail} {action["name"]}'
    if kind == 'timer':
        seconds = f' for {action["seconds"]} s' if action.get('seconds') else ''
        notify = f', notify "{_clip(action["notify"])}"' if action.get('notify') else ''
        return True, f'Timer {action["name"]}: {action.get("op", "toggle")}{seconds}{notify}'
    if kind == 'profile_lock':
        return True, 'Lock or unlock automatic profile switching'
    if kind == 'clipboard':
        paste = ' and paste it' if action.get('paste') else ''
        return True, f'Copy "{_clip(substitute(action["text"], variables))}" to the clipboard{paste}'
    if kind == 'window':
        process = action.get('process', '')
        who = f'the window of {process}' if process else 'the window in front'
        return True, f'{WINDOW_WORDS[action["op"]]} {who}'
    if kind == 'toggle':
        name = action['variable']
        return True, f'Switch variable {name} to "{toggled(action, variables.get("var:" + name))}"'
    if kind == 'panel_lock':
        return True, {'on': 'Lock the panel', 'off': 'Unlock the panel'}.get(action.get('mode'), 'Lock or unlock the panel')
    if kind == 'plugin':
        return True, f'Send the command {action["command"]} to the plugin {action["plugin"]}'
    if kind == 'homeassistant':  # kept from the Wi-Fi beta, whose panel runs it; this version skips it
        return True, _clip(f'Skip Home Assistant {action.get("action", "")}: it runs only on the beta firmware with Wi-Fi')
    return False, f'Unknown action type {kind!r}'


def _plugin_problem(plugin_id, plugins) -> str:
    """Why a step for this plugin would fail, in the words the press itself uses; '' when it can run."""
    known = next((item for item in plugins if isinstance(item, dict) and item.get('id') == plugin_id), None)
    if known is None:
        return f'The plugin {plugin_id} is not installed: put its folder in the plugins folder'
    name = known.get('name') or plugin_id
    if not known.get('enabled'):
        return f'{name} is off: turn it on in More → Plugins'
    if known.get('state') == 'failed':
        return f'{name} has stopped: turn it off and on in More → Plugins'
    if known.get('state') == 'waiting':
        return f'{name} is waiting for its secret: unlock the keyring, or type it again in the editor'
    return f'{name} has stopped' if known.get('state') == 'crashed' else ''


def preview(actions: list[dict], variables: dict[str, str], environment=None, locator=locate, plugins=None) -> dict:
    """What `actions` would do, step by step, using the panel's current variable values. `plugins` is the host's
    list of plugins and their states; None when the host is not running and nothing is known."""
    steps, waited = [], 0.0
    for index, action in enumerate(actions, 1):
        try:
            ok, text = _step(action, variables, environment, locator)
            if ok and plugins is not None and action.get('type') == 'plugin':
                problem = _plugin_problem(action.get('plugin'), plugins)
                ok, text = (False, problem) if problem else (ok, text)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            ok, text = False, f'Cannot run this step: {exc}'
        if ok and action.get('type') == 'delay':
            waited += action.get('ms', 100) / 1000
        steps.append({'index': index, 'type': action.get('type') if isinstance(action, dict) else None,
                      'ok': ok, 'text': text})
    return {'ok': all(step['ok'] for step in steps), 'steps': steps, 'wait_seconds': round(waited, 3),
            'executed': False}
