"""Adapters turn what AI coding tools can report into panel variables.

An adapter is a function from an event (the JSON the tool hands to its hook) to `{variable: value}`. The
`deckctl adapter NAME` command feeds it and sends the result to the running host, so labels, key colors
(`status`) and toggle states can follow the tool. Only fields the tools document are used; nothing is guessed.

  claude   Claude Code hooks (JSON on stdin): UserPromptSubmit, PreToolUse, PostToolUse, Notification, Stop,
           SubagentStop, SessionStart, SessionEnd.
  codex    Codex `notify` program (JSON as the last argument): agent-turn-complete. Codex reports nothing while it
           works, so "working" for Codex still comes from the process detection ($(agent:codex)).
  generic  any tool: `deckctl adapter generic NAME STATE [MESSAGE]`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePath
from typing import Callable

MAX_INPUT = 1024 * 1024
NAME = re.compile(r'[A-Za-z0-9_-]{1,32}')
CLAUDE_EVENTS = ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'Notification', 'Stop',
                 'SubagentStop', 'SessionEnd')


def short(value, limit: int = 60) -> str:
    text = ' '.join(str(value or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _project(cwd) -> str:
    return short(PurePath(str(cwd or '').replace('\\', '/')).name, 40)


def claude(event: dict) -> dict[str, str]:
    """State (working / waiting / idle / ended), the tool in use, the project folder and the last notice."""
    name = event.get('hook_event_name')
    updates: dict[str, str] = {}
    project = _project(event.get('cwd'))
    if project:
        updates['claude.project'] = project
    if name in ('UserPromptSubmit', 'PostToolUse'):
        updates['claude'] = 'working'
    elif name == 'PreToolUse':
        updates.update({'claude': 'working', 'claude.tool': short(event.get('tool_name'), 30)})
    elif name == 'Notification':
        updates.update({'claude': 'waiting', 'claude.message': short(event.get('message'))})
    elif name in ('Stop', 'SubagentStop', 'SessionStart'):
        updates.update({'claude': 'idle', 'claude.tool': '', 'claude.message': ''})
    elif name == 'SessionEnd':
        updates.update({'claude': 'ended', 'claude.tool': '', 'claude.message': ''})
    else:
        return {}
    return updates


def codex(event: dict) -> dict[str, str]:
    """A finished turn: state idle, the project folder and the start of the last answer."""
    if event.get('type') != 'agent-turn-complete':
        return {}
    updates = {'codex': 'idle', 'codex.message': short(event.get('last-assistant-message'))}
    project = _project(event.get('cwd'))
    if project:
        updates['codex.project'] = project
    return updates


def generic(name: str, state: str, message: str = '') -> dict[str, str]:
    if not NAME.fullmatch(name or ''):
        raise ValueError('The tool name must be 1-32 letters, digits, dashes or underscores')
    return {name: short(state, 30), f'{name}.message': short(message)}


ADAPTERS: dict[str, Callable[[dict], dict[str, str]]] = {'claude': claude, 'codex': codex}


def parse_event(text: str) -> dict:
    """The JSON object a tool sent; anything unreadable counts as no event (hooks must never break the tool)."""
    if not text or len(text) > MAX_INPUT:
        return {}
    try:
        event = json.loads(text)
    except ValueError:
        return {}
    return event if isinstance(event, dict) else {}


def claude_hooks(command: str) -> dict:
    """The `hooks` block to merge into ~/.claude/settings.json; every event runs `command`."""
    entry = {'hooks': [{'type': 'command', 'command': command}]}
    return {'hooks': {event: [dict(entry, matcher='*') if event in ('PreToolUse', 'PostToolUse') else dict(entry)]
                      for event in CLAUDE_EVENTS}}


def deckctl_command(python: Path, deckctl: Path) -> str:
    return f'"{python}" "{deckctl}" adapter claude'
