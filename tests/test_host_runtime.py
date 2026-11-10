"""Host tests, part two: runtime status, sensors, toggle keys, the control API, focus, reloads and triggers."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from io import BytesIO
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import psutil
import tesserad as deck
from system_stats import select_hwinfo_metrics
from deck_assets import Assets
from deck_control import Controller, autostart_enabled, set_autostart
from host_support import HostCase, args


class HostRuntimeTests(HostCase):
    def test_runtime_file_publishes_live_gauges_for_the_active_page(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profiles.json'
            path.write_text((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'), encoding='utf-8')
            daemon = deck.Daemon(args(path))
            daemon.panel = Mock()
            daemon.log = Mock()
            daemon.page = 'status'
            daemon.stats.raw = {'cpu_load': 42.0, 'cpu_temp': 91.0}
            daemon.publish_runtime(True, force=True)
            published = json.loads(daemon.runtime_path.read_text(encoding='utf-8'))
            self.assertEqual(published['gauges']['1'], {'p': 42, 't': '42%', 'b': 'lc:e038', 'color': '#35D07F'})
            self.assertEqual(published['gauges']['3']['color'], '#FF7070')
            self.assertEqual(published['gauges']['7'], {'p': 0, 't': '--', 'b': 'lc:e038', 'color': '#4A5A63'})
            daemon.page = 'main'
            daemon.publish_runtime(True, force=True)
            self.assertEqual(json.loads(daemon.runtime_path.read_text(encoding='utf-8'))['gauges'], {})

    def test_libre_hardware_monitor_tree_maps_to_the_right_cpu_and_gpu_metrics(self):
        from sensor_sources import flatten_sensor_tree
        def sensor(text, sensor_id, value):
            return {'Text': text, 'SensorId': sensor_id, 'Value': value, 'Children': []}
        tree = {'Text': 'Sensor', 'Children': [{'Text': 'PC', 'Children': [
            {'Text': 'AMD Ryzen 7 7800X3D', 'Children': [
                {'Text': 'Powers', 'Children': [sensor('Package', '/amdcpu/0/power/0', '26,5 W')]},
                {'Text': 'Clocks', 'Children': [sensor('Cores (Average)', '/amdcpu/0/clock/9', '3874,0 MHz'),
                                                 sensor('Bus Speed', '/amdcpu/0/clock/8', '100,0 MHz')]},
                {'Text': 'Temperatures', 'Children': [sensor('Core (Tctl/Tdie)', '/amdcpu/0/temperature/2', '57,8 °C')]}]},
            {'Text': 'AMD Radeon(TM) Graphics', 'Children': [
                {'Text': 'Temperatures', 'Children': [sensor('GPU VR SoC', '/gpu-amd/0/temperature/1', '41,0 °C')]}]},
            {'Text': 'AMD Radeon RX 6950 XT', 'Children': [
                {'Text': 'Powers', 'Children': [sensor('GPU Package', '/gpu-amd/5/power/0', '48,0 W')]},
                {'Text': 'Clocks', 'Children': [sensor('GPU Core', '/gpu-amd/5/clock/0', '313,0 MHz')]},
                {'Text': 'Temperatures', 'Children': [sensor('GPU Core', '/gpu-amd/5/temperature/0', '46,0 °C'),
                                                      sensor('GPU Hot Spot', '/gpu-amd/5/temperature/2', '56,0 °C')]},
                {'Text': 'Fans', 'Children': [sensor('GPU Fan', '/gpu-amd/5/fan/0', '301 RPM')]}]}]}]}
        metrics = select_hwinfo_metrics(flatten_sensor_tree(tree))
        self.assertEqual(metrics['cpu_temp'], 57.8)
        self.assertEqual(metrics['cpu_power'], 26.5)  # not the GPU's package power
        self.assertEqual(metrics['cpu_clock'], 3874.0)
        self.assertEqual(metrics['gpu_temp'], 46.0)
        self.assertEqual(metrics['gpu_power'], 48.0)
        self.assertEqual(metrics['gpu_clock'], 313.0)
        self.assertEqual(metrics['gpu_fan'], 301.0)

    def toggle_daemon(self):
        daemon = self.daemon()
        page = daemon.config['profiles']['main']['pages']['main']
        page[0]['states'] = [{'label': 'Mic on', 'color': '#35D07F'}, {'label': 'Mic off', 'color': '#FF7070'}]
        page[0]['actions'] = []
        page[1]['actions'] = [{'type': 'state', 'button': page[0]['id'], 'state': 1}]
        daemon.push_page = Mock()
        return daemon, page

    def test_state_action_validates_button_and_state(self):
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
        button = config['profiles']['main']['pages']['main'][0]
        for good in ({'type': 'state', 'button': 3, 'state': 1}, {'type': 'state', 'button': 18, 'state': 'next'},
                     {'type': 'state', 'button': 1}):
            button['actions'] = [good]
            deck.validate_config(config)
        for bad in ({'type': 'state'}, {'type': 'state', 'button': 0}, {'type': 'state', 'button': '2'},
                    {'type': 'state', 'button': True}, {'type': 'state', 'button': 2, 'state': 8},
                    {'type': 'state', 'button': 2, 'state': -1}, {'type': 'state', 'button': 2, 'state': 'last'},
                    {'type': 'state', 'button': 2, 'state': 1.5}):
            with self.subTest(bad):
                button['actions'] = [bad]
                with self.assertRaises(ValueError):
                    deck.validate_config(config)

    def test_state_action_sets_another_buttons_state_and_updates_the_panel(self):
        daemon, page = self.toggle_daemon()
        self.assertEqual(daemon.current_buttons()[0]['label'], 'Mic on')
        self.assertTrue(daemon.dispatch_press(page[1]['id']))
        self.assertEqual(daemon.current_buttons()[0]['label'], 'Mic off')
        self.assertEqual(daemon.current_buttons()[0]['color'], '#FF7070')
        daemon.push_page.assert_called()
        page[1]['actions'] = [{'type': 'state', 'button': page[0]['id'], 'state': 0}]
        daemon.dispatch_press(page[1]['id'])
        self.assertEqual(daemon.current_buttons()[0]['label'], 'Mic on')

    def test_state_next_cycles_and_unknown_targets_fail_cleanly(self):
        daemon, page = self.toggle_daemon()
        page[1]['actions'] = [{'type': 'state', 'button': page[0]['id'], 'state': 'next'}]
        for expected in ('Mic off', 'Mic on', 'Mic off'):
            daemon.dispatch_press(page[1]['id'])
            self.assertEqual(daemon.current_buttons()[0]['label'], expected)
        page[1]['actions'] = [{'type': 'state', 'button': page[2]['id'], 'state': 0}]
        self.assertFalse(daemon.dispatch_press(page[1]['id']))
        self.assertIn('no states', daemon.last_action['error'])
        page[1]['actions'] = [{'type': 'state', 'button': 17, 'state': 0}]
        page[:] = [b for b in page if b['id'] != 17]
        self.assertFalse(daemon.dispatch_press(page[1]['id']))
        self.assertIn('does not exist', daemon.last_action['error'])

    def test_state_action_on_its_own_button_replaces_the_automatic_toggle(self):
        daemon, page = self.toggle_daemon()
        page[0]['actions'] = [{'type': 'state', 'button': page[0]['id'], 'state': 0}]
        daemon.button_states[('main', 'main', page[0]['id'])] = 1
        daemon.dispatch_press(page[0]['id'])
        self.assertEqual(daemon.current_buttons()[0]['label'], 'Mic on')
        page[0]['actions'] = []
        daemon.dispatch_press(page[0]['id'])
        self.assertEqual(daemon.current_buttons()[0]['label'], 'Mic off')

    def test_variables_render_empty_until_set_and_set_by_api_jobs(self):
        daemon = self.daemon()
        daemon.push_page = Mock()
        self.assertEqual(daemon.substitute('Claude $(var:claude)'), 'Claude ')
        daemon.handle_job(('var', 'claude', 'working'))
        self.assertEqual(daemon.substitute('Claude $(var:claude)'), 'Claude working')
        daemon.push_page.assert_called()

    def test_status_variable_colors_the_button(self):
        daemon = self.daemon()
        button = daemon.config['profiles']['main']['pages']['main'][0]
        button['status'] = {'var': 'claude', 'colors': {'working': '#FFB74D', 'waiting': '#FF7070'}}
        deck.validate_config(daemon.config)
        base = daemon.current_buttons()[0]['color']
        daemon.custom_vars['claude'] = 'waiting'
        self.assertEqual(daemon.current_buttons()[0]['color'], '#FF7070')
        daemon.custom_vars['claude'] = 'other'
        self.assertEqual(daemon.current_buttons()[0]['color'], base)
        for bad in ({'var': ''}, {'var': 'x', 'colors': {'a': 'red'}}, {'var': 'x', 'colors': 'no'}, 'x'):
            with self.subTest(bad):
                button['status'] = bad
                with self.assertRaises(ValueError):
                    deck.validate_config(daemon.config)

    def test_api_jobs_press_state_feedback_and_dim(self):
        daemon, page = self.toggle_daemon()
        page[1]['actions'] = [{'type': 'delay', 'ms': 0}]
        daemon.dimmed = True
        daemon.handle_job(('api-press', page[1]['id']))
        self.assertFalse(daemon.dimmed)
        self.assertEqual(daemon.last_action['label'], page[1]['label'])
        daemon.handle_job(('state', page[0]['id'], 'next'))
        self.assertEqual(daemon.current_buttons()[0]['label'], 'Mic off')
        daemon.handle_job(('feedback', 3, False))
        daemon.panel.feedback.assert_called_with(3, False)
        daemon.handle_job(('dim',))
        self.assertTrue(daemon.dimmed)

    def api_server(self):
        from control_api import ControlServer
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        daemon = self.daemon()
        daemon.submit = Mock()
        daemon.connection_failed = threading.Event()
        info = Path(directory.name) / 'api.json'
        server = ControlServer(daemon, info)
        server.start()
        self.addCleanup(server.stop)
        return daemon, server, info

    def api_call(self, info, method, path, data=None, headers=None):
        import urllib.error
        import urllib.request
        saved = json.loads(info.read_text(encoding='utf-8'))
        request = urllib.request.Request(f'http://127.0.0.1:{saved["port"]}{path}', method=method,
            data=None if data is None else json.dumps(data).encode(),
            headers=dict({'X-Deck-Token': saved['token'], 'Content-Type': 'application/json'}, **(headers or {})))
        try:
            with urllib.request.urlopen(request, timeout=3) as reply:
                return reply.status, json.loads(reply.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_control_api_queues_validated_commands_for_the_daemon(self):
        daemon, server, info = self.api_server()
        self.assertEqual(self.api_call(info, 'POST', '/v1/var', {'name': 'claude', 'value': 'working'})[0], 200)
        daemon.submit.assert_called_with(('var', 'claude', 'working'))
        self.api_call(info, 'POST', '/v1/press', {'button': 3})
        daemon.submit.assert_called_with(('api-press', 3))
        self.api_call(info, 'POST', '/v1/state', {'button': 2, 'state': 1})
        daemon.submit.assert_called_with(('state', 2, 1))
        self.api_call(info, 'POST', '/v1/feedback', {'button': 4, 'ok': False})
        daemon.submit.assert_called_with(('feedback', 4, False))
        self.api_call(info, 'POST', '/v1/display', {'action': 'dim'})
        daemon.submit.assert_called_with(('dim',))
        self.api_call(info, 'POST', '/v1/page', {'profile': 'coding', 'page': 'git'})
        daemon.submit.assert_called_with(('wake',), ('profile', 'coding'), ('page', 'git'))

    def test_control_api_rejects_bad_input_and_unauthorised_callers(self):
        daemon, server, info = self.api_server()
        for path, body in (('/v1/var', {'name': 'bad name'}), ('/v1/var', {'name': 'x', 'value': 'v' * 201}),
                           ('/v1/press', {'button': 0}), ('/v1/press', {'button': '3'}),
                           ('/v1/state', {'button': 2, 'state': 8}), ('/v1/feedback', {'button': 2, 'ok': 'yes'}),
                           ('/v1/display', {'action': 'explode'}), ('/v1/page', {'profile': 'nope'}),
                           ('/v1/page', {'page': 'nope'}), ('/v1/nothing', {})):
            with self.subTest(path=path, body=body):
                self.assertIn(self.api_call(info, 'POST', path, body)[0], (400, 404))
        daemon.submit.assert_not_called()
        self.assertEqual(self.api_call(info, 'POST', '/v1/press', {'button': 1}, {'X-Deck-Token': 'wrong'})[0], 401)
        self.assertEqual(self.api_call(info, 'POST', '/v1/press', {'button': 1}, {'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.api_call(info, 'POST', '/v1/press', {'button': 1}, {'Host': 'evil.example'})[0], 403)
        daemon.submit.assert_not_called()

    def test_control_api_reports_state_and_removes_its_info_file_on_stop(self):
        daemon, server, info = self.api_server()
        daemon.custom_vars['claude'] = 'idle'
        status, state = self.api_call(info, 'GET', '/v1/state')
        self.assertEqual(status, 200)
        self.assertEqual((state['profile'], state['variables']), (daemon.profile, {'claude': 'idle'}))
        server.stop()
        self.assertFalse(info.exists())

    def test_deckctl_talks_to_the_host_and_fails_cleanly_without_one(self):
        import deckctl
        daemon, server, info = self.api_server()
        self.assertEqual(deckctl.main(['var', 'claude', 'waiting'], info), 0)
        daemon.submit.assert_called_with(('var', 'claude', 'waiting'))
        self.assertEqual(deckctl.main(['state', '3', '2'], info), 0)
        daemon.submit.assert_called_with(('state', 3, 1))
        self.assertEqual(deckctl.main(['alert', '5'], info), 0)
        daemon.submit.assert_called_with(('feedback', 5, False))
        self.assertEqual(deckctl.main(['press', '99'], info), 1)
        missing = Path(tempfile.mkdtemp()) / 'none.json'
        self.assertEqual(deckctl.main(['wake'], missing), 1)

    def test_unicode_labels_match_the_firmware_byte_limit(self):
        daemon = self.daemon()
        daemon.config['profiles']['main']['pages']['main'][0]['label'] = 'é' * 20
        label = daemon.current_buttons()[0]['label']
        self.assertEqual(label, 'é' * 12)

    def test_folder_and_back_restore_previous_page(self):
        daemon = self.daemon()
        daemon.panel.push_buttons = Mock()
        daemon.panel.send_line = Mock()
        daemon.switch_page('system', folder=True)
        self.assertEqual((daemon.page, daemon.folder_stack), ('system', ['main']))
        daemon.run_action({'type': 'back'})
        self.assertEqual((daemon.page, daemon.folder_stack), ('main', []))

    def test_pinned_button_overrides_same_slot_on_every_page(self):
        daemon = self.daemon()
        daemon.config['profiles']['main']['pinned'] = [
            {'id': 18, 'label': 'Pinned', 'icon': 'home', 'color': '#35D07F', 'actions': []}]
        daemon.page = 'system'
        button = next(item for item in daemon.current_buttons() if item['id'] == 18)
        self.assertEqual(button['label'], 'Pinned')

    def test_toggle_advances_only_after_success(self):
        daemon = self.daemon()
        button = daemon.config['profiles']['main']['pages']['main'][0]
        button['actions'] = []
        button['states'] = [{'label': 'Off'}, {'label': 'On'}]
        self.assertTrue(daemon.dispatch_press(button['id']))
        self.assertEqual(daemon.current_buttons()[0]['label'], 'On')
        button['actions'] = [{'type': 'shell', 'command': 'synthetic'}]
        with patch.object(deck.subprocess, 'run', return_value=types.SimpleNamespace(returncode=1)):
            self.assertFalse(daemon.dispatch_press(button['id']))
        self.assertEqual(daemon.current_buttons()[0]['label'], 'On')

    def test_custom_image_is_normalized_and_content_addressed(self):
        import base64
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / 'profiles.json'
            output = BytesIO()
            Image.new('RGBA', (180, 90), '#35D07F').save(output, format='PNG')
            result = Assets(profile).import_image(base64.b64encode(output.getvalue()).decode())
            self.assertRegex(result['id'], r'^im:[0-9a-f]{12}$')
            self.assertEqual((result['width'], result['height'], result['frames']), (72, 72, 1))
            self.assertTrue(Assets(profile).read(result['id']).startswith(b'ADI1'))

    def test_invalid_image_has_a_clean_validation_error(self):
        import base64
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'could not be read'):
                Assets(Path(directory) / 'profiles.json').import_image(
                    base64.b64encode(b'not an image').decode())

    def test_failed_actions_give_negative_feedback(self):
        daemon = self.daemon()
        daemon.run_action = Mock(side_effect=RuntimeError('blocked'))
        self.assertFalse(daemon.dispatch_press(1))
        daemon.panel.feedback.assert_called_with(1, False)
        self.assertEqual(daemon.last_action['label'], 'Chrome')
        self.assertFalse(daemon.last_action['ok'])
        self.assertEqual(daemon.last_action['error'], 'blocked')

    def test_failed_shell_reports_exit_status(self):
        daemon = self.daemon()
        with patch.object(deck.subprocess, 'run', return_value=types.SimpleNamespace(returncode=7)):
            with self.assertRaises(RuntimeError):
                daemon.run_action({'type': 'shell', 'command': 'synthetic'})

    def test_recursive_press_is_bounded(self):
        daemon = self.daemon()
        daemon.config['profiles']['main']['pages']['main'][0]['actions'] = [{'type': 'press', 'id': 1}]
        self.assertFalse(daemon.dispatch_press(1))
        self.assertEqual(daemon.active_press, [])

    def test_triggers_of_same_type_do_not_fire_each_other(self):
        daemon = self.daemon()
        daemon.config['triggers'] = [
            {'when': {'type': 'interval', 'seconds': 5}, 'actions': [{'type': 'text', 'text': 'a'}]},
            {'when': {'type': 'interval', 'seconds': 10}, 'actions': [{'type': 'text', 'text': 'b'}]}]
        daemon.trigger_tick(100)
        self.assertTrue(daemon.jobs.empty())
        daemon.trigger_tick(105)
        self.assertEqual(daemon.jobs.get_nowait()[1][0]['text'], 'a')
        self.assertTrue(daemon.jobs.empty())

    def test_focus_returns_to_default(self):
        daemon = self.daemon()
        daemon.args.no_focus = False
        daemon.profile = 'coding'
        daemon.auto_profile = 'coding'
        context = {'exe': 'notepad.exe', 'title': 'Notepad', 'processes': ['notepad.exe']}
        with patch.object(deck, 'foreground_context', return_value=context):
            daemon.focus_tick()
        self.assertEqual(daemon.jobs.get_nowait(), ('focus-profile', 'main'))

    def test_long_press_runs_the_hold_actions_and_is_flagged_in_the_layout(self):
        daemon = self.daemon()
        button = next(b for b in daemon.config['profiles']['main']['pages']['main'] if b['id'] == 1)
        button['hold_actions'] = [{'type': 'set', 'variable': 'held', 'value': 'yes'}]
        button['actions'] = [{'type': 'set', 'variable': 'held', 'value': 'no'}]
        daemon.profile, daemon.page = 'main', 'main'
        self.assertTrue(next(b for b in daemon.current_buttons() if b['id'] == 1)['hold'])
        self.assertNotIn('hold', next(b for b in daemon.current_buttons() if b['id'] == 2))
        daemon.handle_job(('press', 1, None, True))
        self.assertEqual(daemon.custom_vars['held'], 'yes')
        daemon.handle_job(('press', 1, None, False))
        self.assertEqual(daemon.custom_vars['held'], 'no')
        button['hold_actions'] = [{'type': 'hotkey', 'keys': 'not-a-key'}]
        with self.assertRaises(ValueError):
            deck.validate_config(daemon.config)

    def test_focus_returns_to_the_profile_that_was_active_before_the_auto_switch(self):
        daemon = self.daemon()
        daemon.args.no_focus = False
        daemon.profile = 'Codex'
        daemon.config['profiles']['coding']['match'] = ['code.exe']
        with patch.object(deck, 'foreground_context',
                          return_value={'exe': 'code.exe', 'title': 'Editor', 'processes': ['code.exe']}):
            daemon.focus_tick()
        self.assertEqual(daemon.jobs.get_nowait(), ('focus-profile', 'coding'))
        daemon.profile = 'coding'
        with patch.object(deck, 'foreground_context',
                          return_value={'exe': 'notepad.exe', 'title': 'Notepad', 'processes': ['notepad.exe']}):
            daemon.focus_tick()
        self.assertEqual(daemon.jobs.get_nowait(), ('focus-profile', 'Codex'))
        self.assertIsNone(daemon.profile_before_auto)

    def test_manual_home_is_not_immediately_overridden_by_focus(self):
        daemon = self.daemon()
        daemon.args.no_focus = False
        daemon.foreground = {'exe': 'chatgpt.exe', 'title': 'ChatGPT', 'processes': ['chatgpt.exe']}
        daemon.config['profiles']['coding']['match'] = ['chatgpt.exe']
        daemon.switch_profile('main')
        with patch.object(deck, 'foreground_context', return_value=daemon.foreground):
            daemon.focus_tick()
        self.assertTrue(daemon.jobs.empty())
        changed = {'exe': 'notepad.exe', 'title': 'Notepad', 'processes': ['notepad.exe']}
        with patch.object(deck, 'foreground_context', return_value=changed):
            daemon.focus_tick()
        self.assertEqual(daemon.manual_focus_exe, '')

    def test_home_returns_to_default_first_page(self):
        daemon = self.daemon()
        daemon.profile = 'main'
        daemon.page = 'system'
        daemon.folder_stack = ['main']
        daemon.run_action({'type': 'home'})
        self.assertEqual((daemon.profile, daemon.page, daemon.folder_stack), ('main', 'main', []))
        daemon.panel.push_buttons.assert_called()

    def test_auto_profile_switching_can_be_disabled(self):
        daemon = self.daemon()
        daemon.args.no_focus = False
        daemon.config['auto_profiles'] = False
        with patch.object(deck, 'foreground_context') as foreground:
            daemon.focus_tick()
        foreground.assert_not_called()
        self.assertTrue(daemon.jobs.empty())

    def test_open_action_focuses_existing_process(self):
        daemon = self.daemon()
        action = {'type': 'open', 'target': 'example.exe', 'process': 'example.exe', 'reuse': True}
        with patch.object(deck, 'IS_WINDOWS', True), \
             patch.object(deck, 'focus_existing_process', return_value=True) as focus, \
             patch.object(deck.os, 'startfile', create=True) as start:
            daemon.run_action(action)
        focus.assert_called_once_with('example.exe')
        start.assert_not_called()

    def test_terminal_profiles_match_child_process_or_title(self):
        context = {'exe': 'windowsterminal.exe', 'title': 'Claude - prosjekt',
                   'processes': ['windowsterminal.exe', 'openconsole.exe', 'claude.exe']}
        self.assertTrue(deck.matches_foreground('process:claude.exe', context))
        self.assertTrue(deck.matches_foreground('title:claude', context))
        self.assertFalse(deck.matches_foreground('process:codex.exe', context))

    def test_focus_selects_terminal_child_profile(self):
        daemon = self.daemon()
        daemon.args.no_focus = False
        daemon.config['profiles']['coding']['match'] = ['process:claude.exe']
        context = {'exe': 'windowsterminal.exe', 'title': 'Terminal',
                   'processes': ['windowsterminal.exe', 'claude.exe']}
        with patch.object(deck, 'foreground_context', return_value=context):
            daemon.focus_tick()
        self.assertEqual(daemon.jobs.get_nowait(), ('focus-profile', 'coding'))

    def test_agent_status_variables_follow_running_processes(self):
        daemon = self.daemon()
        processes = [types.SimpleNamespace(info={'name': 'claude.exe'}),
                     types.SimpleNamespace(info={'name': 'ZCode.exe'})]
        with patch.object(psutil, 'process_iter', return_value=processes):
            daemon.agent_tick(1)
        self.assertEqual(daemon.agents, {'codex': False, 'claude': True, 'zcode': True})
        self.assertEqual(daemon.substitute('Claude $(agent:claude)'), 'Claude ON')

    def test_invalid_profile_reload_preserves_accepted_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profiles.json'
            original = (ROOT / 'host/profiles.default.json').read_text(encoding='utf-8')
            path.write_text(original, encoding='utf-8')
            daemon = deck.Daemon(args(path))
            daemon.log = Mock()
            accepted = copy.deepcopy(daemon.config)
            path.write_text('{', encoding='utf-8')
            daemon.profile_stamp = -1
            daemon.reload_profiles()
            self.assertEqual(accepted, daemon.config)

    def test_missing_profile_file_does_not_stop_daemon(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profiles.json'
            path.write_text((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'), encoding='utf-8')
            daemon = deck.Daemon(args(path))
            daemon.log = Mock()
            accepted = copy.deepcopy(daemon.config)
            path.unlink()
            daemon.reload_profiles()
            self.assertEqual(accepted, daemon.config)
            daemon.log.assert_called_once()

    def test_windows_venv_launcher_tracks_actual_interpreter(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller()
            controller.pid_path = Path(directory) / 'owner.json'
            controller.pid_path.write_text(json.dumps({'pid': 10, 'created': 100}))
            launcher = Mock()
            launcher.pid = 10
            launcher.create_time.return_value = 100
            launcher.cmdline.return_value = ['python.exe', str(ROOT / 'host/tesserad.py')]
            actual = Mock()
            actual.pid = 11
            actual.create_time.return_value = 101
            actual.cmdline.return_value = launcher.cmdline.return_value
            launcher.children.return_value = [actual]
            with patch('deck_control.psutil.Process', return_value=launcher):
                self.assertEqual(controller.processes(), [actual])
            self.assertEqual(json.loads(controller.pid_path.read_text())['pid'], 11)

    def test_reused_process_id_is_not_owned(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller()
            controller.pid_path = Path(directory) / 'owner.json'
            controller.pid_path.write_text(json.dumps({'pid': 10, 'created': 100}))
            controller.runtime_path = Path(directory) / 'runtime.json'  # no host reports from here
            process = Mock()
            process.create_time.return_value = 200
            process.cmdline.return_value = ['python.exe', str(ROOT / 'host/tesserad.py')]
            with patch('deck_control.psutil.Process', return_value=process):
                self.assertEqual(controller.processes(), [])

    def test_a_host_started_elsewhere_is_adopted_from_its_runtime_file(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller()
            controller.pid_path = Path(directory) / 'owner.json'
            controller.runtime_path = Path(directory) / 'runtime.json'
            controller.runtime_path.write_text(json.dumps({'pid': 42}))
            process = Mock()
            process.pid = 42
            process.create_time.return_value = 300
            process.cmdline.return_value = ['python.exe', str(ROOT / 'host/tesserad.py')]
            with patch('deck_control.psutil.Process', return_value=process):
                self.assertEqual(controller.processes(), [process])
            self.assertEqual(json.loads(controller.pid_path.read_text()), {'pid': 42, 'created': 300})
            process.cmdline.return_value = ['python.exe', 'something_else.py']  # the pid now belongs to another program
            controller.pid_path.unlink()
            with patch('deck_control.psutil.Process', return_value=process):
                self.assertEqual(controller.processes(), [])

    def test_controller_reports_confirmed_device_context(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller()
            controller.runtime_path = Path(directory) / 'runtime.json'
            process = Mock(pid=77)
            controller.processes = Mock(return_value=[process])
            controller.runtime_path.write_text(json.dumps({
                'pid': 77, 'updated': __import__('time').time(), 'connected': True,
                'port': 'COM4', 'profile': 'main', 'page': 'apps', 'buttons': 8,
                'last_action': {'id': 2, 'label': 'ChatGPT', 'ok': True, 'at': 10},
                'vars': {'claude': 'working'}, 'stats': {'cpu_temp': '58'}}))
            status = controller.status()
            self.assertTrue(status['device']['connected'])
            self.assertEqual((status['device']['profile'], status['device']['page']), ('main', 'apps'))
            self.assertEqual(status['device']['last_action']['label'], 'ChatGPT')
            # The editor previews $(var:…) and $(stat:…) labels with these values.
            self.assertEqual((status['vars'], status['stats']), ({'claude': 'working'}, {'cpu_temp': '58'}))

    def test_controller_rejects_stale_runtime_status(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller()
            controller.runtime_path = Path(directory) / 'runtime.json'
            controller.processes = Mock(return_value=[Mock(pid=77)])
            controller.runtime_path.write_text(json.dumps({'pid': 77, 'updated': 1, 'connected': True}))
            self.assertFalse(controller.status()['device']['connected'])

    def test_windows_autostart_script_can_be_enabled_and_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            fake_root = Path(directory) / 'program'
            (fake_root / 'host/.venv/Scripts').mkdir(parents=True)
            (fake_root / 'host/.venv/Scripts/pythonw.exe').write_bytes(b'')  # a fresh checkout has no virtual environment
            with patch('deck_control.os.name', 'nt'), patch('deck_control.ROOT', fake_root):
                path = set_autostart(True, directory)
                self.assertTrue(autostart_enabled(directory))
                self.assertIn('tessera_tray.py', path.read_text(encoding='utf-8'))
                self.assertIn('pythonw.exe', path.read_text(encoding='utf-8'))
                set_autostart(False, directory)
                self.assertFalse(autostart_enabled(directory))

    def test_trigger_targets_must_be_text_so_a_bad_one_cannot_stop_the_host(self):
        config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        for when in ({'type': 'file', 'path': ['x']}, {'type': 'file', 'path': 5},
                     {'type': 'file', 'path': 'a' + chr(0) + 'b'}, {'type': 'variable', 'name': ['x']}):
            config['triggers'] = [{'when': when, 'actions': []}]
            with self.assertRaises(ValueError, msg=when):
                deck.validate_config(config)

    def test_saving_the_configuration_does_not_rerun_a_daily_trigger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profiles.json'
            config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
            config['triggers'] = [{'when': {'type': 'daily', 'at': '00:00'}, 'actions': [{'type': 'back'}]}]
            path.write_text(json.dumps(config), encoding='utf-8')
            daemon = deck.Daemon(args(path))
            daemon.log = Mock()
            daemon.trigger_tick(1)
            self.assertEqual(daemon.jobs.get_nowait()[0], 'actions')
            config['display'] = {'brightness': 50}  # an unrelated change
            path.write_text(json.dumps(config), encoding='utf-8')
            daemon.profile_stamp = 0
            daemon.reload_profiles()
            while not daemon.jobs.empty():
                daemon.jobs.get_nowait()
            daemon.trigger_tick(2)
            self.assertTrue(daemon.jobs.empty(), 'the trigger already ran today')

    def test_a_slow_trigger_runs_beside_the_key_queue_and_never_twice_at_once(self):
        daemon = self.daemon()
        started, release = threading.Event(), threading.Event()

        def run_action(action):
            started.set()
            release.wait(5)
        daemon.run_action = run_action
        actions = [{'type': 'delay', 'ms': 1}]
        daemon.handle_job(('actions', actions))  # returns at once: the wait happens on the slow lane
        self.assertTrue(started.wait(5))
        daemon.handle_job(('actions', actions))
        self.assertIn('skipped', daemon.log.call_args[0][0])
        release.set()
        for _ in range(100):
            if not daemon.slow_running:
                break
            time.sleep(.02)
        self.assertFalse(daemon.slow_running)

    def test_without_a_panel_a_page_change_is_remembered_instead_of_failing(self):
        daemon = self.daemon()
        daemon.panel = None
        daemon.last_push = 'old'
        daemon.push_page(force=True)  # triggers, timers and profile switches keep working while unplugged
        self.assertIsNone(daemon.last_push, 'the page is sent in full when a panel connects')

    def test_focusing_a_maximized_window_does_not_shrink_it(self):
        user32 = Mock()
        user32.IsIconic.return_value = False  # maximized or normal: SW_RESTORE would un-maximize it
        deck.bring_to_front(user32, 7)
        user32.ShowWindow.assert_not_called()
        user32.SetForegroundWindow.assert_called_once_with(7)
        user32.IsIconic.return_value = True  # minimized: restore it first
        deck.bring_to_front(user32, 7)
        user32.ShowWindow.assert_called_once_with(7, 9)


if __name__ == '__main__':
    unittest.main()
