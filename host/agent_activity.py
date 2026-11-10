"""What the AI tools are doing, read from the session files they already write: no hook is needed for this.

Claude Code appends to ~/.claude/projects/<project>/<session>.jsonl and Codex to ~/.codex/sessions/.../rollout-*.jsonl
while they work. A file written to a moment ago means "working"; the project folder and the last tool come from the
file itself. Hooks (deckctl adapter ...) still win when they report a state, and they are the only way to see
"waiting for you".
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

WORKING_SECONDS = 15   # a session file written this recently means the tool is busy
RECENT_SECONDS = 3600  # an idle tool is listed for an hour after its last work, then only when its program runs
SCAN_SECONDS = 2
TAIL_BYTES = 16384
HEAD_BYTES = 4096
CWD = re.compile(rb'"cwd":"((?:[^"\\]|\\.)*)"')
TOOL = re.compile(rb'"type":"tool_use","id":"[^"]*","name":"([A-Za-z0-9_-]{1,40})"')


def _newest(paths):
    best = (0.0, None)
    for path in paths:
        try:
            modified = os.stat(path).st_mtime
        except OSError:
            continue
        if modified > best[0]:
            best = (modified, path)
    return best


def _claude_files(root: Path):
    try:
        for project in os.scandir(root):
            if project.is_dir():
                try:
                    for entry in os.scandir(project.path):
                        if entry.name.endswith('.jsonl'):
                            yield entry.path
                except OSError:
                    continue
    except OSError:
        return


def _codex_files(root: Path):
    for folder, _, names in os.walk(root):
        for name in names:
            if name.endswith('.jsonl'):
                yield os.path.join(folder, name)


def _read(path, tail: bool, size: int) -> bytes:
    try:
        with open(path, 'rb') as stream:
            if tail:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - size))
            return stream.read(size)
    except OSError:
        return b''


def project_of(data: bytes) -> str:
    """The folder name of the last cwd mentioned in `data`, or ''."""
    found = CWD.findall(data)
    if not found:
        return ''
    path = found[-1].decode('utf-8', 'replace').replace('\\\\', '\\').replace('\\/', '/')
    return re.split(r'[\\/]', path.rstrip('\\/'))[-1][:30]


class AgentActivity:
    def __init__(self, claude_root=None, codex_root=None, clock=time.time):
        home = Path.home()
        self.roots = {'claude': (Path(claude_root) if claude_root else home / '.claude' / 'projects', _claude_files),
                      'codex': (Path(codex_root) if codex_root else home / '.codex' / 'sessions', _codex_files)}
        self._clock = clock
        self._cache: dict = {}
        self._scanned_at = float('-inf')

    def read(self) -> dict:
        """{'claude': {'state': 'working'|'idle', 'project': …, 'tool': …, 'age': seconds}, …}; only tools with a session file."""
        now = self._clock()
        if now - self._scanned_at < SCAN_SECONDS:
            return self._cache
        self._scanned_at = now
        result = {}
        for key, (root, files) in self.roots.items():
            modified, path = _newest(files(root))
            if path is None:
                continue
            age = max(0.0, now - modified)
            working = age <= WORKING_SECONDS
            tail = _read(path, True, TAIL_BYTES)
            project = project_of(tail) or project_of(_read(path, False, HEAD_BYTES))
            tools = TOOL.findall(tail)
            result[key] = {'state': 'working' if working else 'idle', 'project': project, 'age': age,
                           'tool': tools[-1].decode('ascii', 'replace') if working and tools else ''}
        self._cache = result
        return result


def merge(variables: dict, activity: dict, running: dict, clock=time.time) -> dict:
    """The variables the agents screen is drawn from: what a hook reported wins, the session files fill the rest."""
    merged = dict(variables)
    stamp = time.strftime('%H:%M', time.localtime(clock()))
    for key, seen in activity.items():
        if str(variables.get(key, '')) in ('working', 'waiting'):
            merged.setdefault(f'{key}.project', seen['project'])
            continue
        if seen['state'] == 'working':
            merged[key] = 'working'
            merged.setdefault(f'{key}.tool', seen['tool'])
        elif seen['age'] <= RECENT_SECONDS or running.get(key):
            merged[key] = 'idle'
            moment = time.localtime(clock() - seen['age'])
            when = time.strftime('%H:%M' if seen['age'] < 20 * 3600 else '%d %b', moment)
            merged.setdefault(f'{key}.message', f'Last active {when}' if when != stamp else 'Just finished')
        if seen['project']:
            merged.setdefault(f'{key}.project', seen['project'])
    return merged
