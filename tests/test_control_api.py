"""The control API's HTTP surface: tokens, browser and Host checks, body limit, scoped grants, rate limit and audit."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import control_api  # noqa: E402
import plugins  # noqa: E402
from control_api import ControlServer  # noqa: E402


class ControlApiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.daemon = Mock()
        self.daemon.config = {'profiles': {}}
        self.daemon.events = plugins.EventLog()
        self.daemon.jobs.qsize.return_value = 0
        self.daemon.jobs.maxsize = 64
        for name, value in (('profile', 'p'), ('page', 'main'), ('panel', None), ('dimmed', False), ('locked', False),
                            ('custom_vars', {}), ('agents', {}), ('dropped_jobs', 0), ('slow_running', [])):
            setattr(self.daemon, name, value)
        self.logged = []
        self.daemon.log = self.logged.append
        self.api = ControlServer(self.daemon, Path(temp.name) / 'api.json')
        self.api.start()  # binds port 0: a free port
        self.addCleanup(self.api.stop)
        self.port = self.api.server.server_port

    def call(self, method, path, data=None, token=None, headers=None, raw=None):
        body = raw if raw is not None else None if data is None else json.dumps(data).encode()
        sent = {'Content-Type': 'application/json'}
        if token is not False:
            sent['X-Deck-Token'] = token or self.api.token
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', method=method, data=body,
                                         headers=dict(sent, **(headers or {})))
        try:
            with urllib.request.urlopen(request, timeout=3) as reply:
                return reply.status, json.loads(reply.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_missing_or_wrong_token_is_refused(self):
        self.assertEqual(self.call('POST', '/v1/press', {'button': 1}, token=False)[0], 401)
        self.assertEqual(self.call('POST', '/v1/press', {'button': 1}, token='wrong')[0], 401)
        self.assertEqual(self.call('GET', '/v1/state', token='wrong')[0], 401)
        self.daemon.submit.assert_not_called()

    def test_browser_requests_and_other_hosts_are_refused(self):
        for headers in ({'Origin': 'http://evil.example'}, {'Origin': 'null'}, {'Host': 'evil.example'},
                        {'Host': f'localhost:{self.port}'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.call('POST', '/v1/press', {'button': 1}, headers=headers)[0], 403)
        self.daemon.submit.assert_not_called()

    def test_an_oversized_body_is_refused_before_it_is_read(self):
        big = json.dumps({'name': 'x', 'value': 'v' * (control_api.MAX_BODY + 10)}).encode()
        self.assertEqual(self.call('POST', '/v1/var', raw=big)[0], 413)
        self.daemon.submit.assert_not_called()

    def test_a_plugin_token_can_only_call_what_it_was_granted(self):
        token = self.api.add_grant('demo', {'var'}, 'demo.')
        self.assertEqual(self.call('POST', '/v1/var', {'name': 'demo.a', 'value': '1'}, token=token)[0], 200)
        self.assertEqual(self.call('POST', '/v1/var', {'name': 'other', 'value': '1'}, token=token)[0], 403)
        for path, body in (('/v1/press', {'button': 1}), ('/v1/vars', {'set': {'demo.a': '1'}}),
                           ('/v1/display', {'action': 'dim'}), ('/v1/permission', {})):
            with self.subTest(path=path):
                self.assertEqual(self.call('POST', path, body, token=token)[0], 403)
        self.assertEqual(self.call('GET', '/v1/state', token=token)[0], 403)
        self.assertEqual(self.call('GET', '/v1/events', token=token)[0], 403)
        self.assertEqual(self.daemon.submit.call_count, 1)
        self.api.remove_grant(token)
        self.assertEqual(self.call('POST', '/v1/var', {'name': 'demo.a', 'value': '1'}, token=token)[0], 401)

    def test_each_token_is_rate_limited_with_a_burst(self):
        now = [100.0]
        self.api.clock = lambda: now[0]
        token = self.api.add_grant('demo', {'var'}, 'demo.')
        codes = [self.call('POST', '/v1/var', {'name': 'demo.a', 'value': '1'}, token=token)[0]
                 for _ in range(control_api.RATE_BURST + 1)]
        self.assertEqual(codes[:-1], [200] * control_api.RATE_BURST)
        self.assertEqual(codes[-1], 429)
        self.assertEqual(self.call('GET', '/v1/state')[0], 200)  # another token has its own budget
        now[0] += 2 / control_api.RATE_PER_SECOND  # refilled at the steady rate
        self.assertEqual(self.call('POST', '/v1/var', {'name': 'demo.a', 'value': '1'}, token=token)[0], 200)

    def test_changes_are_logged_with_the_caller_but_never_the_body(self):
        token = self.api.add_grant('demo', {'var'}, 'demo.')
        self.call('POST', '/v1/var', {'name': 'demo.a', 'value': 'hunter2'}, token=token)
        self.call('POST', '/v1/press', {'button': 1}, token=token)
        self.call('POST', '/v1/press', {'button': 1}, token='wrong')
        self.call('GET', '/v1/state')
        self.assertEqual(self.logged, ['API demo POST /v1/var -> 200', 'API demo POST /v1/press -> 403',
                                       'API unknown POST /v1/press -> 401'])
        self.assertFalse(any(token in line or 'hunter2' in line for line in self.logged))


if __name__ == '__main__':
    unittest.main()
