#!/usr/bin/env python3
"""Command line control for a running Tessera host.

Examples:
  deckctl var claude working     set a variable (labels use $(var:claude))
  deckctl press 3                press button 3
  deckctl page main status       show a page
  deckctl state 3 next           set a toggle button's state (next or 1-8)
  deckctl ok 3 / deckctl alert 3 flash a button green or red
  deckctl wake / deckctl dim     wake or dim the panel
  deckctl status                 print the host state as JSON
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

INFO_PATH = Path(__file__).with_name('deck-api.local.json')
TIMEOUT = 3.0


class DeckctlError(Exception):
    """A failure to report on stderr with a non-zero exit code."""


def load_info(path: Path = INFO_PATH) -> dict:
    try:
        info = json.loads(Path(path).read_text(encoding='utf-8'))
        return {'port': int(info['port']), 'token': str(info['token'])}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DeckctlError('The Tessera host is not running (no control API found).') from exc


def call(info: dict, method: str, path: str, data: dict | None = None):
    url = f'http://127.0.0.1:{info["port"]}{path}'
    body = None if data is None else json.dumps(data).encode('utf-8')
    request = urllib.request.Request(url, data=body, method=method,
                                     headers={'X-Deck-Token': info['token'], 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:
            return json.loads(reply.read())
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read()).get('error', exc.reason)
        except (ValueError, OSError):
            message = exc.reason
        raise DeckctlError(f'The host rejected the request: {message}') from exc
    except (urllib.error.URLError, OSError) as exc:
        raise DeckctlError('Could not reach the Tessera host.') from exc


def state_value(text: str):
    """'next' stays 'next'; 1-8 becomes the 0-based index the API uses."""
    if text == 'next':
        return 'next'
    if text.isdigit() and 1 <= int(text) <= 8:
        return int(text) - 1
    raise argparse.ArgumentTypeError("state must be 'next' or a number from 1 to 8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='deckctl', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    variable = commands.add_parser('var', help='set a variable')
    variable.add_argument('name')
    variable.add_argument('value')
    for name in ('press', 'ok', 'alert'):
        commands.add_parser(name).add_argument('button', type=int)
    page = commands.add_parser('page', help='show a page')
    page.add_argument('profile')
    page.add_argument('page', nargs='?')
    state = commands.add_parser('state', help="set a toggle button's state")
    state.add_argument('button', type=int)
    state.add_argument('state', nargs='?', type=state_value, default='next')
    for name in ('wake', 'dim', 'status'):
        commands.add_parser(name)
    return parser


def run(arguments: argparse.Namespace, info: dict):
    command = arguments.command
    if command == 'var':
        return call(info, 'POST', '/v1/var', {'name': arguments.name, 'value': arguments.value})
    if command == 'press':
        return call(info, 'POST', '/v1/press', {'button': arguments.button})
    if command in ('ok', 'alert'):
        return call(info, 'POST', '/v1/feedback', {'button': arguments.button, 'ok': command == 'ok'})
    if command == 'page':
        data = {'profile': arguments.profile}
        if arguments.page:
            data['page'] = arguments.page
        return call(info, 'POST', '/v1/page', data)
    if command == 'state':
        return call(info, 'POST', '/v1/state', {'button': arguments.button, 'state': arguments.state})
    if command in ('wake', 'dim'):
        return call(info, 'POST', '/v1/display', {'action': command})
    return call(info, 'GET', '/v1/state')


def main(argv=None, info_path: Path = INFO_PATH) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = run(arguments, load_info(info_path))
    except DeckctlError as exc:
        print(f'deckctl: {exc}', file=sys.stderr)
        return 1
    if arguments.command == 'status':
        print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
