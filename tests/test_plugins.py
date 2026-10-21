"""Plugins: manifests, scoped tokens, events, crash-safe lifecycle and a real example plugin end to end."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import deckctl
import plugins
import tesserad as deck
from control_api import ControlServer


def write_plugin(root: Path, plugin_id='demo', **changes) -> Path:
    folder = root / plugin_id
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {'id': plugin_id, 'name': 'Demo', 'version': '1.0', 'api': 1, 'command': ['python', 'main.py'],
                'permissions': ['vars', 'events']}
    manifest.update(changes)
    (folder / 'plugin.json').write_text(json.dumps(manifest))
    return folder


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_the_bundled_example_is_a_valid_plugin(self):
        manifest = plugins.load_manifest(ROOT / 'plugins' / 'example-uptime')
        self.assertEqual((manifest.id, manifest.permissions), ('example-uptime', frozenset({'vars', 'events'})))
        self.assertEqual(manifest.routes(), frozenset({'var', 'vars'}))
        self.assertEqual(plugins.resolve_command(manifest, 'PY')[0], 'PY')

    def test_invalid_manifests_are_refused_with_a_reason(self):
        cases = ({'api': 2}, {'id': 'Bad Id'}, {'id': 'other-name'}, {'name': ''}, {'version': 5},
                 {'command': []}, {'command': 'python main.py'}, {'command': [5]}, {'permissions': ['root']},
                 {'permissions': ['vars', 'vars']}, {'permissions': 'vars'}, {'settings': []},
                 {'settings': {'Bad': {'type': 'text'}}}, {'settings': {'ok': {'type': 'secret'}}},
                 {'command': ['..\\evil.exe']}, {'command': ['/windows/system32/cmd.exe', '/c', 'calc']})
        for change in cases:
            folder = write_plugin(self.root, **change)
            with self.assertRaises(plugins.ManifestError, msg=repr(change)):
                plugins.load_manifest(folder)
        (self.root / 'broken').mkdir()
        (self.root / 'broken' / 'plugin.json').write_text('{not json')
        with self.assertRaises(plugins.ManifestError):
            plugins.load_manifest(self.root / 'broken')

    def test_programs_must_live_inside_the_plugin_folder(self):
        folder = write_plugin(self.root, command=['tool.exe', '--x'])
        manifest = plugins.load_manifest(folder)
        self.assertEqual(Path(plugins.resolve_command(manifest)[0]).parent, folder.resolve())

    def test_discovery_lists_good_plugins_and_explains_the_bad_ones(self):
        write_plugin(self.root, 'good')
        write_plugin(self.root, 'bad', api=9)
        (self.root / 'not-a-plugin').mkdir()
        found, problems = plugins.discover(self.root)
        self.assertEqual([manifest.id for manifest in found], ['good'])
        self.assertEqual(len(problems), 1)
        self.assertIn('bad', problems[0])

    def test_the_configuration_block_is_validated(self):
        plugins.check_plugin_config({'demo': {'enabled': True, 'settings': {'interval': 5, 'name': 'x', 'on': True}}})
        for bad in ([], {'Demo': {}}, {'demo': {'enabled': 'yes'}}, {'demo': {'enabled': True, 'settings': []}},
                    {'demo': {'enabled': True, 'settings': {'a': [1]}}},
                    {'demo': {'enabled': True, 'settings': {'a': 'x' * 5000}}}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                plugins.check_plugin_config(bad)


class EventLogTests(unittest.TestCase):
    def test_events_are_numbered_filtered_by_addressee_and_bounded(self):
        log = plugins.EventLog(maxlen=5)
        log.add('press', button=1)
        log.add('command', plugin='a', command='go')
        log.add('command', plugin='b', command='stop')
        self.assertEqual([event['type'] for event in log.since(0, 'a')], ['press', 'command'])
        self.assertEqual([event.get('plugin') for event in log.since(0, 'b') if event['type'] == 'command'], ['b'])
        self.assertEqual([event['type'] for event in log.since(0, None)], ['press'])
        for number in range(10):
            log.add('page', page=str(number))
        self.assertEqual(len(log.since(0, 'a', limit=100)), 5)
        self.assertEqual(log.last, 13)

    def test_a_waiting_reader_wakes_up_when_something_happens(self):
        log = plugins.EventLog()
        threading.Timer(0.2, lambda: log.add('press', button=3)).start()
        started = time.monotonic()
        events = log.since(0, 'a', wait=5)
        self.assertEqual(events[0]['button'], 3)
        self.assertLess(time.monotonic() - started, 3)

    def test_waiting_without_news_returns_empty_after_the_timeout_and_is_capped(self):
        log = plugins.EventLog()
        started = time.monotonic()
        self.assertEqual(log.since(0, 'a', wait=0.3), [])
        self.assertGreaterEqual(time.monotonic() - started, 0.25)
        self.assertEqual(plugins.MAX_WAIT_SECONDS, 25)


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.daemon = Mock()
        self.daemon.config = {'profiles': {}}
        self.daemon.events = plugins.EventLog()
        self.daemon.jobs.qsize.return_value = 0
        self.api = ControlServer(self.daemon, Path(self.temp.name) / 'api.json')
        self.api.start()
        self.addCleanup(self.api.stop)
        self.owner = deckctl.load_info(Path(self.temp.name) / 'api.json')

    def info(self, token):
        return dict(self.owner, token=token)

    def test_a_plugin_token_can_only_use_its_routes_and_its_own_variable_names(self):
        token = self.api.add_grant('demo', {'var', 'vars'}, 'demo.', events=True)
        mine = self.info(token)
        deckctl.call(mine, 'POST', '/v1/var', {'name': 'demo.text', 'value': 'hi'})
        deckctl.call(mine, 'POST', '/v1/vars', {'set': {'demo.a': '1', 'demo.b': '2'}})
        self.assertEqual(self.daemon.submit.call_count, 2)
        for path, data in (('/v1/var', {'name': 'claude', 'value': 'x'}),
                           ('/v1/vars', {'set': {'demo.ok': '1', 'claude': 'working'}}),
                           ('/v1/press', {'button': 1}), ('/v1/feedback', {'button': 1}),
                           ('/v1/page', {'profile': 'main'}), ('/v1/display', {'action': 'dim'})):
            with self.assertRaises(deckctl.DeckctlError, msg=path) as raised:
                deckctl.call(mine, 'POST', path, data)
            self.assertIn('rejected', str(raised.exception))
        self.assertEqual(self.daemon.submit.call_count, 2, 'nothing from a refused request was queued')

    def test_state_is_hidden_without_the_read_permission(self):
        quiet = self.info(self.api.add_grant('quiet', set(), 'quiet.'))
        with self.assertRaises(deckctl.DeckctlError):
            deckctl.call(quiet, 'GET', '/v1/state')
        with self.assertRaises(deckctl.DeckctlError):
            deckctl.call(quiet, 'GET', '/v1/events')
        reader = self.info(self.api.add_grant('reader', set(), 'reader.', read=True))
        with patch.object(self.api, 'snapshot', return_value={'profile': 'main'}):
            self.assertIn('profile', deckctl.call(reader, 'GET', '/v1/state'))

    def test_events_a_plugin_sees_exclude_commands_for_other_plugins(self):
        self.daemon.events.add('press', button=2)
        self.daemon.events.add('command', plugin='other', command='secret')
        self.daemon.events.add('command', plugin='demo', command='mine')
        demo = self.info(self.api.add_grant('demo', set(), 'demo.', events=True))
        reply = deckctl.call(demo, 'GET', '/v1/events?since=0')
        self.assertEqual([event['type'] for event in reply['events']], ['press', 'command'])
        self.assertEqual(reply['events'][1]['command'], 'mine')
        self.assertEqual(reply['last'], 3)
        owner = deckctl.call(self.owner, 'GET', '/v1/events?since=0')
        self.assertEqual([event['type'] for event in owner['events']], ['press'])

    def test_bad_event_queries_and_unknown_or_revoked_tokens(self):
        with self.assertRaises(deckctl.DeckctlError):
            deckctl.call(self.owner, 'GET', '/v1/events?since=abc')
        token = self.api.add_grant('demo', {'var'}, 'demo.')
        self.api.remove_grant(token)
        with self.assertRaises(deckctl.DeckctlError) as raised:
            deckctl.call(self.info(token), 'POST', '/v1/var', {'name': 'demo.x', 'value': '1'})
        self.assertIn('Invalid token', str(raised.exception))
        self.api.remove_grant(self.api.token)
        with patch.object(self.api, 'snapshot', return_value={'profile': 'main'}):
            deckctl.call(self.owner, 'GET', '/v1/state')  # the owner token cannot be revoked by accident


class FakeProcess:
    def __init__(self):
        self.code = None
        self.terminated = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = 1

    def wait(self, timeout=None):
        return self.code


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_plugin(self.root / 'plugins')
        self.now = [100.0]
        self.spawned, self.grants, self.revoked = [], [], []

        def spawn(argv, **kwargs):
            process = FakeProcess()
            self.spawned.append((argv, kwargs, process))
            return process

        def grant(name, routes, prefix, events, read):
            token = f'token-{len(self.grants)}'
            self.grants.append((name, routes, prefix, events, read, token))
            return token

        self.manager = plugins.PluginManager(self.root / 'plugins', self.root / 'logs', lambda: 'http://127.0.0.1:1',
                                             grant, self.revoked.append, spawn, lambda: self.now[0],
                                             lambda message: None, python='PY')

    def enabled(self, **settings):
        return {'demo': {'enabled': True, 'settings': settings}}

    def test_an_enabled_plugin_is_started_once_with_a_scoped_token_and_a_clean_environment(self):
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'secret', 'PATH': 'p'}):
            self.manager.sync(self.enabled(interval=7))
            self.manager.sync(self.enabled(interval=7))
        self.assertEqual(len(self.spawned), 1)
        argv, kwargs, _ = self.spawned[0]
        self.assertEqual(argv, ['PY', 'main.py'])
        environment = kwargs['env']
        self.assertEqual((environment['TESSERA_TOKEN'], environment['TESSERA_PLUGIN']), ('token-0', 'demo'))
        self.assertEqual(json.loads(environment['TESSERA_SETTINGS']), {'interval': 7})
        self.assertNotIn('GITHUB_TOKEN', environment)
        self.assertEqual(self.grants[0][:5], ('demo', frozenset({'var', 'vars'}), 'demo.', True, False))
        self.assertEqual(Path(kwargs['cwd']).name, 'demo')

    def test_disabling_stops_the_process_and_revokes_its_token(self):
        self.manager.sync(self.enabled())
        self.manager.sync({'demo': {'enabled': False}})
        self.assertTrue(self.spawned[0][2].terminated)
        self.assertEqual(self.revoked, ['token-0'])
        self.assertEqual(self.manager.status({'demo': {'enabled': False}})[0]['state'], 'disabled')

    def test_changed_settings_restart_the_plugin_with_the_new_values(self):
        self.manager.sync(self.enabled(interval=5))
        self.manager.sync(self.enabled(interval=9))
        self.assertEqual(len(self.spawned), 2)
        self.assertEqual(json.loads(self.spawned[1][1]['env']['TESSERA_SETTINGS']), {'interval': 9})
        self.assertEqual(self.revoked, ['token-0'])

    def test_a_crashing_plugin_is_restarted_with_back_off_and_eventually_given_up(self):
        for attempt in range(plugins.MAX_QUICK_CRASHES):
            self.manager.sync(self.enabled())
            self.assertEqual(len(self.spawned), attempt + 1)
            self.spawned[-1][2].code = 3
            self.now[0] += 1
            self.manager.sync(self.enabled())  # notices the crash
            self.now[0] += plugins.BACKOFF_SECONDS[min(attempt, len(plugins.BACKOFF_SECONDS) - 1)] + 0.1
        self.manager.sync(self.enabled())
        self.assertEqual(len(self.spawned), plugins.MAX_QUICK_CRASHES, 'no more attempts after giving up')
        status = self.manager.status(self.enabled())[0]
        self.assertEqual(status['state'], 'failed')
        self.assertIn('stopped with code 3', status['error'])
        self.assertEqual(len(self.revoked), plugins.MAX_QUICK_CRASHES)
        self.manager.sync({'demo': {'enabled': False}})
        self.manager.sync(self.enabled())
        self.assertEqual(len(self.spawned), plugins.MAX_QUICK_CRASHES + 1,
                         'turning it off and on gives a fresh start')

    def test_back_off_delays_the_restart(self):
        self.manager.sync(self.enabled())
        self.spawned[0][2].code = 1
        self.manager.sync(self.enabled())
        self.assertEqual(len(self.spawned), 1)
        self.now[0] += 0.5
        self.manager.sync(self.enabled())
        self.assertEqual(len(self.spawned), 1)
        self.now[0] += 1
        self.manager.sync(self.enabled())
        self.assertEqual(len(self.spawned), 2)

    def test_a_plugin_that_ran_long_enough_starts_counting_crashes_from_zero(self):
        self.manager.sync(self.enabled())
        self.now[0] += plugins.STABLE_SECONDS + 1
        self.spawned[0][2].code = 1
        self.manager.sync(self.enabled())
        self.assertEqual(self.manager.status(self.enabled())[0]['crashes'], 1)

    def test_a_program_that_cannot_start_is_reported_not_raised(self):
        def broken(argv, **kwargs):
            raise OSError('no such file')
        self.manager._spawn = broken
        self.manager.sync(self.enabled())
        status = self.manager.status(self.enabled())[0]
        self.assertEqual(status['state'], 'crashed')
        self.assertIn('could not start', status['error'])
        self.assertEqual(self.revoked, ['token-0'])

    def test_unknown_plugins_in_the_configuration_are_ignored_and_stop_all_cleans_up(self):
        self.manager.sync({'ghost': {'enabled': True}, **self.enabled()})
        self.assertEqual(len(self.spawned), 1)
        self.manager.stop_all()
        self.assertEqual(self.revoked, ['token-0'])
        self.assertEqual(self.manager.running, {})


class DaemonTests(unittest.TestCase):
    def daemon(self):
        daemon = deck.Daemon(types.SimpleNamespace(profiles=str(ROOT / 'host/profiles.default.json'), port='TEST',
                                                   verbose=False, no_focus=True, deck_only=True))
        daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
        return daemon

    def test_the_plugin_action_sends_a_command_event_only_to_that_plugin(self):
        daemon = self.daemon()
        daemon.run_action({'type': 'plugin', 'plugin': 'obs', 'command': 'toggle-recording',
                           'args': {'scene': 'Main'}})
        events = daemon.events.since(0, 'obs')
        self.assertEqual((events[0]['command'], events[0]['args']), ('toggle-recording', {'scene': 'Main'}))
        self.assertEqual(daemon.events.since(0, 'other'), [])

    def test_presses_and_navigation_are_published_as_events(self):
        daemon = self.daemon()
        daemon.profile, daemon.page = 'main', 'main'
        daemon.dispatch_press(1)
        daemon.switch_page('system')
        kinds = [event['type'] for event in daemon.events.since(0, None)]
        self.assertIn('press', kinds)
        self.assertIn('page', kinds)

    def test_the_validator_checks_plugin_actions_and_the_plugins_block(self):
        config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        button = config['profiles']['main']['pages']['main'][0]
        button['actions'] = [{'type': 'plugin', 'plugin': 'demo', 'command': 'go', 'args': {'a': 1}}]
        config['plugins'] = {'demo': {'enabled': True, 'settings': {'interval': 5}}}
        deck.validate_config(config)
        for bad_action in ({'type': 'plugin', 'plugin': 'Bad Id', 'command': 'go'},
                           {'type': 'plugin', 'plugin': 'demo', 'command': 'has space'},
                           {'type': 'plugin', 'plugin': 'demo', 'command': 'go', 'args': 'x'},
                           {'type': 'plugin', 'plugin': 'demo', 'command': 'go', 'args': {'a': 'x' * 2000}},
                           {'type': 'plugin', 'command': 'go'}):
            button['actions'] = [bad_action]
            with self.assertRaises(ValueError, msg=repr(bad_action)):
                deck.validate_config(config)
        button['actions'] = []
        config['plugins'] = {'demo': {'enabled': 'yes'}}
        with self.assertRaises(ValueError):
            deck.validate_config(config)


class EndToEndTests(unittest.TestCase):
    def test_the_example_plugin_runs_for_real_sets_variables_and_obeys_commands(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        daemon = Mock()
        daemon.config = {'profiles': {}}
        daemon.events = plugins.EventLog()
        daemon.jobs.qsize.return_value = 0
        api = ControlServer(daemon, Path(temp.name) / 'api.json')
        api.start()
        self.addCleanup(api.stop)
        manager = plugins.PluginManager(ROOT / 'plugins', Path(temp.name) / 'logs',
                                        lambda: f'http://127.0.0.1:{api.server.server_port}', api.add_grant,
                                        api.remove_grant, log=lambda message: None)
        self.addCleanup(manager.stop_all)
        manager.sync({'example-uptime': {'enabled': True, 'settings': {'interval': 1}}})

        def published():
            return [job for call in daemon.submit.call_args_list for job in call.args
                    if job[1] == 'example-uptime.text']

        for _ in range(100):
            if published():
                break
            time.sleep(0.1)
        self.assertTrue(published(), (Path(temp.name) / 'logs' / 'example-uptime.log').read_text(errors='replace'))
        self.assertEqual(published()[0][2], '0:00:00')
        # a command from a key makes the plugin restart its count
        time.sleep(2.2)
        daemon.submit.reset_mock()
        daemon.events.add('command', plugin='example-uptime', command='reset')
        for _ in range(100):
            texts = [job[2] for job in published()]
            if texts and texts[-1] == '0:00:00':
                break
            time.sleep(0.1)
        self.assertEqual([job[2] for job in published()][-1], '0:00:00')
        manager.stop_all()
        self.assertEqual(manager.running, {})
        with self.assertRaises(deckctl.DeckctlError):
            deckctl.call({'port': api.server.server_port, 'token': 'x'}, 'POST', '/v1/var',
                         {'name': 'a', 'value': 'b'})


if __name__ == '__main__':
    unittest.main()
