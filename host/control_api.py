"""Local control API: lets scripts, hooks and AI tools drive the panel.

Listens on 127.0.0.1 only. Every request needs the per-run token that is written to
deck-api.local.json (readable by the same Windows user only), and browser requests
(anything with an Origin header) are rejected so a web page cannot reach it.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
from action_runner import Busy
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MAX_BODY = 64 * 1024
VARIABLE_NAME = re.compile(r'[A-Za-z0-9_.-]{1,64}')
MAX_VALUE = 200


class ApiError(ValueError):
    """A request the API rejects with HTTP 400."""


class Forbidden(ApiError):
    """A request the caller's token does not allow (HTTP 403)."""


@dataclass(frozen=True)
class Grant:
    """What one token may do: routes (None = everything), a variable-name prefix, and the two read routes."""
    name: str
    routes: frozenset | None = None
    prefix: str | None = None
    events: bool = True
    read: bool = True


def _button(data) -> int:
    value = data.get('button')
    if type(value) is not int or not 1 <= value <= 18:
        raise ApiError('button must be a whole number from 1 to 18')
    return value


class ControlServer:
    def __init__(self, daemon, info_path):
        self.daemon = daemon
        self.info_path = Path(info_path)
        self.token = secrets.token_urlsafe(32)
        self.grants = {self.token: Grant('owner')}
        self.grant_lock = threading.Lock()
        self.server: ThreadingHTTPServer | None = None
        self.routes = {'var': self.set_variable, 'vars': self.set_variables, 'press': self.press, 'page': self.show_page,
                       'state': self.set_state, 'feedback': self.feedback, 'display': self.display}

    # --- scoped tokens for plugins -----------------------------------------------------
    def add_grant(self, name, routes, prefix=None, events=False, read=False) -> str:
        token = secrets.token_urlsafe(32)
        with self.grant_lock:
            self.grants[token] = Grant(name, frozenset(routes), prefix, events, read)
        return token

    def remove_grant(self, token) -> None:
        with self.grant_lock:
            if token != self.token:
                self.grants.pop(token, None)

    def grant_for(self, supplied):
        with self.grant_lock:
            found = None
            for token, grant in self.grants.items():
                if secrets.compare_digest(supplied, token):
                    found = grant
            return found

    @staticmethod
    def check_scope(grant, route, data):
        if grant.routes is not None and route not in grant.routes:
            raise Forbidden(f'This token may not use {route}')
        if grant.prefix and route in ('var', 'vars'):
            names = [data.get('name')] if route == 'var' else list(data.get('set') or {}) if isinstance(data.get('set'), dict) else []
            if any(not isinstance(name, str) or not name.startswith(grant.prefix) for name in names):
                raise Forbidden(f'Variables of this plugin must start with {grant.prefix}')

    def events(self, query, grant):
        try:
            since = int(query.get('since', ['0'])[0])
            wait = float(query.get('wait', ['0'])[0])
        except ValueError as exc:
            raise ApiError('since must be a whole number and wait a number of seconds') from exc
        plugin = None if grant.name == 'owner' else grant.name
        return {'events': self.daemon.events.since(since, plugin, wait), 'last': self.daemon.events.last}

    # --- request handlers: validate, then queue work for the daemon's worker thread ---
    def set_variable(self, data):
        name, value = data.get('name'), data.get('value', '')
        if not isinstance(name, str) or not VARIABLE_NAME.fullmatch(name):
            raise ApiError('name must be 1-64 letters, digits, dots, dashes or underscores')
        if not isinstance(value, (str, int, float)) or isinstance(value, bool) or len(str(value)) > MAX_VALUE:
            raise ApiError(f'value must be text or a number of at most {MAX_VALUE} characters')
        self.daemon.submit(('var', name, str(value)))

    def set_variables(self, data):
        # Several variables in one request, queued all-or-nothing (used by the AI tool adapters).
        values = data.get('set')
        if not isinstance(values, dict) or not 1 <= len(values) <= 20:
            raise ApiError('set must be an object with 1 to 20 variables')
        jobs = []
        for name, value in values.items():
            if not isinstance(name, str) or not VARIABLE_NAME.fullmatch(name):
                raise ApiError('name must be 1-64 letters, digits, dots, dashes or underscores')
            if not isinstance(value, (str, int, float)) or isinstance(value, bool) or len(str(value)) > MAX_VALUE:
                raise ApiError(f'value must be text or a number of at most {MAX_VALUE} characters')
            jobs.append(('var', name, str(value)))
        self.daemon.submit(*jobs)

    def press(self, data):
        self.daemon.submit(('api-press', _button(data)))

    def show_page(self, data):
        config = self.daemon.config['profiles']
        profile = data.get('profile', self.daemon.profile)
        if profile not in config:
            raise ApiError(f'Unknown profile: {profile}')
        page = data.get('page', next(iter(config[profile]['pages'])))
        if page not in config[profile]['pages']:
            raise ApiError(f'Unknown page: {page}')
        self.daemon.submit(('wake',), ('profile', profile), ('page', page))

    def set_state(self, data):
        value = data.get('state', 'next')
        if value != 'next' and (type(value) is not int or not 0 <= value <= 7):
            raise ApiError("state must be 'next' or a whole number from 0 to 7")
        self.daemon.submit(('state', _button(data), value))

    def feedback(self, data):
        if type(data.get('ok', True)) is not bool:
            raise ApiError('ok must be true or false')
        self.daemon.submit(('feedback', _button(data), data.get('ok', True)))

    def display(self, data):
        action = data.get('action')
        if action not in ('wake', 'dim'):
            raise ApiError("action must be 'wake' or 'dim'")
        self.daemon.submit((action,))

    def snapshot(self):
        daemon = self.daemon
        return {'profile': daemon.profile, 'page': daemon.page, 'connected': daemon.panel is not None
                and not daemon.connection_failed.is_set(), 'dimmed': daemon.dimmed, 'locked': daemon.locked,
                'variables': dict(daemon.custom_vars), 'agents': dict(daemon.agents),
                'queue': {'pending': daemon.jobs.qsize(), 'capacity': daemon.jobs.maxsize,
                          'dropped': daemon.dropped_jobs, 'slow_running': len(daemon.slow_running)}}

    # --- HTTP plumbing ---------------------------------------------------------------
    def make_handler(self):
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, code, payload):
                raw = json.dumps(payload).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(raw)

            def authorized(self):
                host = f'127.0.0.1:{self.server.server_port}'
                if self.headers.get('Host') != host or self.headers.get('Origin'):
                    self.reply(403, {'error': 'Forbidden'})
                    return None
                grant = api.grant_for(self.headers.get('X-Deck-Token', ''))
                if grant is None:
                    self.reply(401, {'error': 'Invalid token'})
                return grant

            def do_GET(self):
                grant = self.authorized()
                if grant is None:
                    return
                url = urlparse(self.path)
                if url.path == '/v1/state':
                    return self.reply(200, api.snapshot()) if grant.read else self.reply(403, {'error': 'This token may not read the state'})
                if url.path == '/v1/events':
                    if not grant.events:
                        return self.reply(403, {'error': 'This token may not read events'})
                    try:
                        return self.reply(200, api.events(parse_qs(url.query), grant))
                    except ApiError as exc:
                        return self.reply(400, {'error': str(exc)})
                self.reply(404, {'error': 'Not found'})

            def do_POST(self):
                grant = self.authorized()
                if grant is None:
                    return
                route = self.path.removeprefix('/v1/') if self.path.startswith('/v1/') else None
                handler = api.routes.get(route)
                if handler is None:
                    return self.reply(404, {'error': 'Not found'})
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    if not 0 <= length <= MAX_BODY:
                        return self.reply(413, {'error': 'Request too large'})
                    data = json.loads(self.rfile.read(length) or b'{}')
                    if not isinstance(data, dict):
                        raise ApiError('The body must be a JSON object')
                    api.check_scope(grant, route, data)
                    handler(data)
                except Busy as exc:
                    return self.reply(503, {'error': str(exc), 'retry': True})
                except Forbidden as exc:
                    return self.reply(403, {'error': str(exc)})
                except (ValueError, TypeError) as exc:
                    return self.reply(400, {'error': str(exc)})
                self.reply(200, {'ok': True, 'queued': True})

        return Handler

    def start(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.make_handler())
        self.server.daemon_threads = True
        self.server.handle_error = lambda request, client_address: None  # a client that hangs up is not an error
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        info = {'pid': os.getpid(), 'port': self.server.server_port, 'token': self.token}
        temporary = self.info_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(info), encoding='utf-8')
        os.replace(temporary, self.info_path)

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        self.info_path.unlink(missing_ok=True)
