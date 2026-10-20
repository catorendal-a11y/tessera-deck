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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 64 * 1024
VARIABLE_NAME = re.compile(r'[A-Za-z0-9_.-]{1,64}')
MAX_VALUE = 200


class ApiError(ValueError):
    """A request the API rejects with HTTP 400."""


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
        self.server: ThreadingHTTPServer | None = None
        self.routes = {'var': self.set_variable, 'press': self.press, 'page': self.show_page,
                       'state': self.set_state, 'feedback': self.feedback, 'display': self.display}

    # --- request handlers: validate, then queue work for the daemon's worker thread ---
    def set_variable(self, data):
        name, value = data.get('name'), data.get('value', '')
        if not isinstance(name, str) or not VARIABLE_NAME.fullmatch(name):
            raise ApiError('name must be 1-64 letters, digits, dots, dashes or underscores')
        if not isinstance(value, (str, int, float)) or isinstance(value, bool) or len(str(value)) > MAX_VALUE:
            raise ApiError(f'value must be text or a number of at most {MAX_VALUE} characters')
        self.daemon.enqueue(('var', name, str(value)))

    def press(self, data):
        self.daemon.enqueue(('api-press', _button(data)))

    def show_page(self, data):
        config = self.daemon.config['profiles']
        profile = data.get('profile', self.daemon.profile)
        if profile not in config:
            raise ApiError(f'Unknown profile: {profile}')
        page = data.get('page', next(iter(config[profile]['pages'])))
        if page not in config[profile]['pages']:
            raise ApiError(f'Unknown page: {page}')
        self.daemon.enqueue(('wake',))
        self.daemon.enqueue(('profile', profile))
        self.daemon.enqueue(('page', page))

    def set_state(self, data):
        value = data.get('state', 'next')
        if value != 'next' and (type(value) is not int or not 0 <= value <= 7):
            raise ApiError("state must be 'next' or a whole number from 0 to 7")
        self.daemon.enqueue(('state', _button(data), value))

    def feedback(self, data):
        if type(data.get('ok', True)) is not bool:
            raise ApiError('ok must be true or false')
        self.daemon.enqueue(('feedback', _button(data), data.get('ok', True)))

    def display(self, data):
        action = data.get('action')
        if action not in ('wake', 'dim'):
            raise ApiError("action must be 'wake' or 'dim'")
        self.daemon.enqueue((action,))

    def snapshot(self):
        daemon = self.daemon
        return {'profile': daemon.profile, 'page': daemon.page, 'connected': daemon.panel is not None
                and not daemon.connection_failed.is_set(), 'dimmed': daemon.dimmed, 'locked': daemon.locked,
                'variables': dict(daemon.custom_vars), 'agents': dict(daemon.agents)}

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
                    return False
                if not secrets.compare_digest(self.headers.get('X-Deck-Token', ''), api.token):
                    self.reply(401, {'error': 'Invalid token'})
                    return False
                return True

            def do_GET(self):
                if not self.authorized():
                    return
                if self.path == '/v1/state':
                    return self.reply(200, api.snapshot())
                self.reply(404, {'error': 'Not found'})

            def do_POST(self):
                if not self.authorized():
                    return
                handler = api.routes.get(self.path.removeprefix('/v1/')) if self.path.startswith('/v1/') else None
                if handler is None:
                    return self.reply(404, {'error': 'Not found'})
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    if not 0 <= length <= MAX_BODY:
                        return self.reply(413, {'error': 'Request too large'})
                    data = json.loads(self.rfile.read(length) or b'{}')
                    if not isinstance(data, dict):
                        raise ApiError('The body must be a JSON object')
                    handler(data)
                except (ValueError, TypeError) as exc:
                    return self.reply(400, {'error': str(exc)})
                self.reply(200, {'ok': True})

        return Handler

    def start(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.make_handler())
        self.server.daemon_threads = True
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
