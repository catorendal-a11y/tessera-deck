"""The control API's HTTP surface: tokens, browser and Host checks, body limit, scoped grants, rate limit and audit."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

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

    def test_a_route_that_fails_unexpectedly_answers_and_leaves_a_line_in_the_log(self):
        self.api.routes['page'] = Mock(side_effect=KeyError('pages'))
        status, body = self.call('POST', '/v1/page', {'page': 'main'})
        self.assertEqual(status, 500)
        self.assertIn('host log', body['error'])
        self.assertTrue(any('page' in line and 'KeyError' in line for line in self.logged))

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

    def test_an_authorized_reply_proves_the_host_knows_the_token(self):
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}/v1/state',
                                         headers={'X-Deck-Token': self.api.token, 'X-Deck-Nonce': 'abc123'})
        with urllib.request.urlopen(request, timeout=3) as reply:
            self.assertEqual(reply.headers['X-Deck-Proof'], control_api.proof(self.api.token, 'abc123'))
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}/v1/state',
                                         headers={'X-Deck-Token': 'wrong', 'X-Deck-Nonce': 'abc123'})
        with self.assertRaises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request, timeout=3)
        with refused.exception as error:
            self.assertIsNone(error.headers['X-Deck-Proof'])

    def test_the_port_cannot_be_bound_a_second_time_while_the_host_runs(self):
        with socket.socket() as second:
            if hasattr(socket, 'SO_REUSEADDR'):
                second.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with self.assertRaises(OSError):
                second.bind(('127.0.0.1', self.port))

    def test_a_client_that_trickles_bytes_is_disconnected_at_the_deadline(self):
        with patch.object(control_api, 'REQUEST_DEADLINE', 0.5),                 socket.create_connection(('127.0.0.1', self.port), timeout=0.1) as client:
            started, closed = time.monotonic(), False
            while not closed and time.monotonic() - started < 4:
                try:
                    client.sendall(b'x')  # one byte, well inside the 10 s per read
                    closed = client.recv(1) == b''
                except TimeoutError:
                    pass
                except OSError:
                    closed = True
            self.assertTrue(closed)
            self.assertLess(time.monotonic() - started, 3)

    def test_calls_without_a_token_are_logged_only_now_and_then(self):
        now = [100.0]
        self.api.clock = lambda: now[0]
        for _ in range(5):
            self.call('POST', '/v1/x', {}, token='wrong')
        self.assertEqual(self.logged, ['API unknown POST /v1/x -> 401'])
        now[0] += control_api.UNKNOWN_LOG_SECONDS
        self.call('POST', '/v1/x', {}, token='wrong')
        self.assertEqual(self.logged[1], 'API unknown POST /v1/x -> 401 (and 4 more like it)')

    def test_a_client_that_stalls_is_disconnected(self):
        with patch.object(control_api, 'REQUEST_TIMEOUT', 0.3):
            temp = tempfile.TemporaryDirectory()
            self.addCleanup(temp.cleanup)
            api = ControlServer(self.daemon, Path(temp.name) / 'slow.json')
            api.start()
            self.addCleanup(api.stop)
        with socket.create_connection(('127.0.0.1', api.server.server_port), timeout=5) as client:
            client.sendall(b'POST /v1/press HTTP/1.1\r\nHost: 127.0.0.1')  # and then nothing more
            started = time.monotonic()
            self.assertEqual(client.recv(1024), b'')
            self.assertLess(time.monotonic() - started, 4)

    def test_missing_or_wrong_token_is_refused(self):
        self.assertEqual(self.call('POST', '/v1/press', {'button': 1}, token=False)[0], 401)
        self.assertEqual(self.call('POST', '/v1/press', {'button': 1}, token='wrong')[0], 401)
        self.assertEqual(self.call('GET', '/v1/state', token='wrong')[0], 401)
        self.assertIsNone(self.api.grant_for('é'))  # http.server hands over latin-1 text; it must not raise
        self.daemon.submit.assert_not_called()

    def test_a_non_ascii_token_is_refused_not_dropped(self):
        self.assertEqual(self.call('GET', '/v1/state', token='tøken')[0], 401)

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

    def test_notify_queues_a_short_message_for_the_panel(self):
        self.assertEqual(self.call('POST', '/v1/notify', {'text': '  Build passed ', 'level': 'ok', 'seconds': 3})[0], 200)
        self.daemon.submit.assert_called_with(('notify', 'Build passed', 'ok', 3))
        self.assertEqual(self.call('POST', '/v1/notify', {'text': 'Tests ran'})[0], 200)
        self.daemon.submit.assert_called_with(('notify', 'Tests ran', 'info', control_api.NOTIFY_DEFAULT_SECONDS))
        self.assertEqual(self.call('POST', '/v1/notify', {'text': 'é' * control_api.NOTIFY_MAX_TEXT, 'seconds': 30})[0], 200)

    def assert_not_echoed(self, body, reply):
        sent = body.get('text')
        if isinstance(sent, str) and sent.strip():
            # The reply is JSON, so an echo shows up escaped.
            self.assertNotIn(json.dumps(sent)[1:-1], json.dumps(reply))

    def test_the_not_echoed_check_fails_on_a_reply_that_echoes(self):
        with self.assertRaises(AssertionError):
            self.assert_not_echoed({'text': 'two\nlines'}, {'error': 'bad text two\nlines'})
        self.assert_not_echoed({'text': 'two\nlines'}, {'error': 'text must be one line'})

    def test_notify_refuses_text_level_or_seconds_out_of_bounds(self):
        bad = ({}, {'text': ''}, {'text': '   '}, {'text': 5}, {'text': 'x' * (control_api.NOTIFY_MAX_TEXT + 1)},
               {'text': 'two\nlines'}, {'text': 'tab\there'}, {'text': 'bell\x07'}, {'text': 'line sep'},
               {'text': 'x', 'level': 'loud'}, {'text': 'x', 'level': None}, {'text': 'x', 'seconds': 0},
               {'text': 'x', 'seconds': 31}, {'text': 'x', 'seconds': 2.5}, {'text': 'x', 'seconds': '5'},
               {'text': 'x', 'seconds': True})
        for body in bad:
            with self.subTest(body=body):
                code, reply = self.call('POST', '/v1/notify', body)
                self.assertEqual(code, 400)
                self.assert_not_echoed(body, reply)
        # A lone surrogate cannot be sent as UTF-8; JSON can still carry it.
        self.assertEqual(self.call('POST', '/v1/notify', raw=b'{"text": "a\\ud800b"}')[0], 400)
        self.daemon.submit.assert_not_called()

    def test_notify_needs_its_plugin_permission_and_is_rate_limited(self):
        now = [100.0]
        self.api.clock = lambda: now[0]
        other = self.api.add_grant('demo', {'var'}, 'demo.')
        self.assertEqual(self.call('POST', '/v1/notify', {'text': 'hi'}, token=other)[0], 403)
        token = self.api.add_grant('notes', set(plugins.PERMISSIONS['notify']), 'notes.')
        codes = [self.call('POST', '/v1/notify', {'text': 'hi'}, token=token)[0] for _ in range(control_api.RATE_BURST + 1)]
        self.assertEqual(codes[:-1], [200] * control_api.RATE_BURST)
        self.assertEqual(codes[-1], 429)
        self.assertEqual(self.daemon.submit.call_count, control_api.RATE_BURST)


class OfflinePressTests(unittest.TestCase):
    """deckctl press and a plugin's POST /v1/press while the panel is unplugged: the worker drops panel jobs then, so a
    press that is accepted never runs. The caller must hear it instead of getting OK."""

    def test_a_press_while_the_panel_is_not_connected_is_refused_with_the_reason(self):
        import host_support
        daemon = host_support.test_daemon(port='COM4', no_focus=True)
        daemon.log = Mock()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        api = ControlServer(daemon, Path(temp.name) / 'api.json')
        api.start()
        self.addCleanup(api.stop)
        request = urllib.request.Request(f'http://127.0.0.1:{api.server.server_port}/v1/press', method='POST',
                                         data=b'{"button": 1}', headers={'Content-Type': 'application/json',
                                                                         'X-Deck-Token': api.token})
        with self.assertRaises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request, timeout=3)
        with refused.exception as error:
            self.assertEqual(error.code, 400)
            said = json.loads(error.read())['error']
            self.assertIn('not connected', said)
            self.assertIn('USB cable', said)  # what to do next, not only what went wrong
        self.assertEqual(daemon.jobs.qsize(), 0)


class NoticeTests(unittest.TestCase):
    """The host side of a notice: the panel's banner when its firmware has one, a Windows notification otherwise."""

    def daemon(self, panel=None, info=None, failed=False):
        import threading
        import daemon_display
        from daemon_ticks import BackgroundMixin

        class Daemon(daemon_display.DisplayMixin, BackgroundMixin):
            pass

        daemon = Daemon.__new__(Daemon)
        daemon.panel, daemon.device_info, daemon.notices, daemon.logged = panel, info or {}, [], []
        daemon.connection_failed = threading.Event()
        daemon.dimmed = daemon.locked = daemon.ambient_active = daemon.ambient_requested = False
        if failed:
            daemon.connection_failed.set()
        daemon.log = daemon.logged.append
        return daemon

    def test_a_panel_with_a_banner_gets_the_message(self):
        panel = Mock()
        daemon = self.daemon(panel, {'protocol': 4, 'notify': 1})
        daemon.show_notice('Build passed', 'ok', 5)
        panel.send_line.assert_called_once_with('AD_NOTIFY ok 5 Build passed')
        self.assertEqual(daemon.notices, [])

    def test_without_a_banner_it_becomes_a_windows_notification(self):
        for panel, info, failed in ((None, {'notify': 1}, False), (Mock(), {'protocol': 4}, False),
                                    (Mock(), {'notify': True}, False), (Mock(), {'notify': 1}, True)):
            with self.subTest(info=info, failed=failed):
                daemon = self.daemon(panel, info, failed)
                daemon.show_notice('Build passed', 'ok', 5)
                if panel is not None:
                    panel.send_line.assert_not_called()
                self.assertEqual([(n['title'], n['message']) for n in daemon.notices], [('Tessera', 'Build passed')])

    def test_a_panel_that_fails_to_take_it_falls_back_too(self):
        panel = Mock()
        panel.send_line.side_effect = OSError('gone')
        daemon = self.daemon(panel, {'notify': 1})
        daemon.show_notice('Build passed', 'warn', 5)
        self.assertEqual([n['message'] for n in daemon.notices], ['Build passed'])
        self.assertEqual(len(daemon.logged), 1)

    def test_a_warning_wakes_a_dimmed_panel_unless_windows_is_locked(self):
        for level, locked, wakes in (('warn', False, True), ('error', False, True), ('ok', False, False),
                                     ('info', False, False), ('error', True, False)):
            with self.subTest(level=level, locked=locked):
                panel = Mock()
                daemon = self.daemon(panel, {'notify': 1})
                daemon.dimmed, daemon.locked = True, locked
                daemon.show_notice('Build failed', level, 5)
                lines = [call.args[0] for call in panel.send_line.call_args_list]
                self.assertEqual(lines, (['AD_SCREEN deck', 'AD_DISPLAY_WAKE'] if wakes else [])
                                 + [f'AD_NOTIFY {level} 5 Build failed'])
                self.assertEqual(daemon.dimmed, not wakes)

    def test_the_line_never_carries_a_newline(self):
        panel = Mock()
        self.daemon(panel, {'notify': 1}).show_notice('a\nAD_DIM\r', 'info', 6)
        panel.send_line.assert_called_once_with('AD_NOTIFY info 6 a AD_DIM ')


class DeckctlSayTests(unittest.TestCase):
    def test_say_joins_its_words_and_posts_them(self):
        import deckctl
        parse = deckctl.build_parser().parse_args
        with patch.object(deckctl, 'call', return_value={'ok': True}) as call:
            deckctl.run(parse(['say', 'Build', 'passed', '--level', 'ok', '--seconds', '4']), {})
            deckctl.run(parse(['say', 'Tests ran']), {})
        self.assertEqual([entry.args[1:] for entry in call.call_args_list],
                         [('POST', '/v1/notify', {'text': 'Build passed', 'level': 'ok', 'seconds': 4}),
                          ('POST', '/v1/notify', {'text': 'Tests ran', 'level': 'info', 'seconds': 6})])
        with self.assertRaises(SystemExit), patch('sys.stderr'):
            parse(['say', 'x', '--level', 'loud'])


if __name__ == '__main__':
    unittest.main()
