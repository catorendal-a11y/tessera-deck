"""Answering an AI tool's permission prompt on the panel.

Claude Code runs a PermissionRequest hook before it shows its own dialog. `deckctl permission` is that hook: it
asks the host, the host shows the request on the agents screen, and Allow or Deny on the panel is the answer.
Whenever anything is unclear (no panel, a request too long to show in full, no answer in time) the hook prints
nothing, and the tool falls back to its normal dialog. Nothing here ever allows on its own.
"""
from __future__ import annotations

import json
import re
import threading

MAX_TEXT = 150  # what one lane on the panel shows in full; a longer request is not answered here
WAIT_SECONDS = 25
TOOL = re.compile(r'[A-Za-z0-9_-]{1,64}')
DECISIONS = ('allow', 'deny')
AGENT_IDS = ('claude',)  # the tools whose prompts can be answered here


def printable(text: str) -> bool:
    return all(32 <= ord(char) <= 126 for char in text)


def request_text(payload) -> str:
    """'Bash: npm run build' for a PermissionRequest hook event; ValueError when it cannot be shown in full.

    Every argument is shown except `description`, which only describes the others. A request that does not fit,
    or holds characters the panel cannot draw, is refused rather than approved half-seen.
    """
    if not isinstance(payload, dict) or payload.get('hook_event_name') != 'PermissionRequest':
        raise ValueError('not a permission request')
    tool, arguments = payload.get('tool_name'), payload.get('tool_input')
    if not isinstance(tool, str) or not TOOL.fullmatch(tool) or not isinstance(arguments, dict):
        raise ValueError('unsupported request')
    shown = {key: value for key, value in arguments.items() if key != 'description'}
    if set(shown) == {'command'} and isinstance(shown['command'], str):
        detail = shown['command']
    else:
        detail = json.dumps(shown, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    text = f'{tool}: {detail}'
    if not detail or len(text) > MAX_TEXT or not printable(text):
        raise ValueError('the request cannot be shown in full on the panel')
    return text


def hook_output(decision: str) -> dict:
    if decision not in DECISIONS:
        raise ValueError('no decision')
    return {'hookSpecificOutput': {'hookEventName': 'PermissionRequest', 'decision': {'behavior': decision}}}


class Desk:
    """The one question the panel is showing. A second request while one is open is not taken."""

    def __init__(self, changed=lambda: None):
        self._lock = threading.Lock()
        self._open: dict | None = None
        self._changed = changed

    def current(self) -> dict | None:
        """{'agent', 'text'} of the open question, if any."""
        with self._lock:
            return None if self._open is None else {'agent': self._open['agent'], 'text': self._open['text']}

    def ask(self, agent: str, text: str, ready, timeout: float = WAIT_SECONDS) -> str | None:
        """Show the question and wait for the panel: 'allow', 'deny', or None when nobody answered."""
        if not ready():
            return None
        question = {'agent': agent, 'text': text, 'answered': threading.Event(), 'decision': None}
        with self._lock:
            if self._open is not None:
                return None
            self._open = question
        self._changed()
        try:
            question['answered'].wait(timeout)
        finally:
            with self._lock:
                if self._open is question:
                    self._open = None
            self._changed()
        return question['decision']

    def answer(self, agent: str, decision: str) -> bool:
        """The panel's button; False when no question for that agent is open (the button then does something else)."""
        with self._lock:
            question = self._open
            if question is None or question['agent'] != agent or decision not in DECISIONS:
                return False
            question['decision'] = decision
            self._open = None
        question['answered'].set()
        return True
