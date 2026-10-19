import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from io import BytesIO
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import agent_deckd as deck
from system_stats import SystemStats, select_hwinfo_metrics
from deck_assets import Assets
from deck_control import Controller, autostart_enabled, set_autostart


def args(path=ROOT / 'host/profiles.json'):
    return types.SimpleNamespace(profiles=str(path), port='TEST', verbose=False,
                                 no_focus=True, deck_only=True)


class HostTests(unittest.TestCase):
    def daemon(self, config=None):
        daemon = deck.Daemon(args())
        daemon.panel = Mock()
        daemon.log = Mock()
        daemon.publish_runtime = Mock()
        if config is not None:
            daemon.config = config
        return daemon

    def test_default_profiles_validate_on_all_platforms(self):
        deck.Daemon.load_profiles(ROOT / 'host/profiles.json')

    def test_default_home_is_a_complete_app_launcher(self):
        config = json.loads((ROOT / 'host/profiles.json').read_text(encoding='utf-8'))
        profile = config['profiles']['hoved']
        home = profile['pages']['hoved']
        labels = {button['label'] for button in home}
        self.assertEqual(len(home), 17)
        self.assertTrue({'Chrome', 'ChatGPT', 'ZCode', 'Claude', 'VS Code',
                         'GitHub Desktop', 'Terminal', 'Utforsker', 'Discord',
                         'Obsidian', 'LM Studio', 'Steam', 'Xbox'} <= labels)
        self.assertEqual(profile['pinned'][0]['id'], 18)

    def test_status_page_has_full_live_dashboard(self):
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.json')
        status = config['profiles']['hoved']['pages']['status']
        self.assertEqual(len(status), 17)
        labels = {item['label'] for item in status}
        self.assertIn('CPU $(stat:cpu_temp)°', labels)
        self.assertIn('GPU $(stat:gpu_temp)°', labels)
        self.assertIn('HWiNFO $(stat:sensor_status)', labels)

    def test_hwinfo_metrics_prefer_discrete_gpu(self):
        readings = [
            {'sensor': 'GPU [#0]: AMD Radeon Graphics', 'label': 'GPU Temperature',
             'unit': '°C', 'value': 50},
            {'sensor': 'GPU [#1]: AMD Radeon RX 6950 XT', 'label': 'GPU Temperature',
             'unit': '°C', 'value': 71},
            {'sensor': 'CPU [#0]: AMD Ryzen 7 7800X3D', 'label': 'CPU (Tctl/Tdie)',
             'unit': '°C', 'value': 63},
        ]
        metrics = select_hwinfo_metrics(readings)
        self.assertEqual(metrics['gpu_temp'], 71)
        self.assertEqual(metrics['cpu_temp'], 63)

    def test_status_values_and_warning_color_are_resolved(self):
        daemon = self.daemon()
        daemon.page = 'status'
        daemon.stats.display['cpu_temp'] = '84'
        daemon.stats.raw['cpu_temp'] = 84
        button = next(item for item in daemon.current_buttons() if item['id'] == 1)
        self.assertEqual(button['label'], 'CPU 84°')
        self.assertEqual(button['color'], '#FFB74D')

    def test_letters_use_uppercase_virtual_key_codes(self):
        self.assertEqual(deck.parse_hotkey('ctrl+c'), [0x11, 0x43])
        self.assertEqual(deck.parse_hotkey('ctrl+lbracket'), [0x11, 0xDB])
        self.assertEqual(deck.parse_hotkey('win+period'), [0x5B, 0xBE])

    def test_volume_virtual_keys(self):
        self.assertEqual(deck.VK['volumemute'], 0xad)
        self.assertEqual(deck.VK['volumedown'], 0xae)
        self.assertEqual(deck.VK['volumeup'], 0xaf)

    def test_unknown_modifier_is_rejected(self):
        with self.assertRaises(ValueError):
            deck.parse_hotkey('ctrrl+c')

    def test_all_pressed_keys_are_released_after_failure(self):
        with patch.object(deck, '_key') as key:
            key.side_effect = [None, OSError('blocked'), None]
            with self.assertRaises(OSError):
                deck.send_hotkey('ctrl+c')
            self.assertEqual(key.call_args_list[-1].kwargs, {'vk': 0x11, 'flags': 2})

    def test_unicode_sends_utf16_surrogates(self):
        with patch.object(deck, '_key') as key:
            deck.send_text('\U0001f680')
            self.assertEqual([call.kwargs['scan'] for call in key.call_args_list],
                             [0xd83d, 0xd83d, 0xde80, 0xde80])

    def test_serial_keeps_split_utf8_and_newlines(self):
        panel = deck.PanelSerial.__new__(deck.PanelSerial)
        panel.rx = bytearray()
        panel.ser = Mock()
        panel.ser.in_waiting = 4096
        raw = '{"type":"deck_event","button":1,"label":"Kjør"}\n'.encode()
        split = raw.index('ø'.encode()) + 1
        panel.ser.read.side_effect = [raw[:split], raw[split:] + b'AD_PRESS OK\n']
        self.assertEqual(panel.read_lines(), [])
        lines = panel.read_lines()
        self.assertEqual(json.loads(lines[0])['label'], 'Kjør')
        self.assertEqual(lines[1], 'AD_PRESS OK')

    def test_config_requires_acknowledgment(self):
        panel = deck.PanelSerial.__new__(deck.PanelSerial)
        panel.write_lock = threading.RLock()
        panel.cfg_done = Mock()
        panel.cfg_done.wait.return_value = False
        panel.send_line = Mock()
        with self.assertRaises(TimeoutError):
            panel.push_buttons([{'id': 1, 'label': 'Test'}])

    def test_touch_feedback_also_wakes_a_dark_display(self):
        panel = deck.PanelSerial.__new__(deck.PanelSerial)
        panel.send_line = Mock()
        panel.feedback(7, True)
        self.assertEqual([call.args[0] for call in panel.send_line.call_args_list],
                         ['AD_DISPLAY_WAKE', 'AD_FEEDBACK ok 7'])

    def test_page_push_wakes_display_before_repainting(self):
        daemon = self.daemon()
        daemon.panel.push_assets = Mock()
        daemon.panel.push_buttons = Mock()
        daemon.panel.send_line = Mock()
        daemon.push_page(force=True)
        daemon.panel.send_line.assert_any_call('AD_DISPLAY_WAKE')
        daemon.panel.push_buttons.assert_called_once()

    def test_1024x600_panel_is_enabled_after_controller_init(self):
        source = (ROOT / 'components/espressif__esp32_p4_function_ev_board/'
                  'esp32_p4_function_ev_board.c').read_text(encoding='utf-8')
        init = source.index('esp_lcd_panel_init(disp_panel)')
        display_on = source.index('esp_lcd_panel_disp_on_off(disp_panel, true)', init)
        self.assertGreater(display_on, init)

    def test_duplicate_button_ids_are_rejected(self):
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.json')
        buttons = config['profiles']['hoved']['pages']['hoved']
        buttons[1]['id'] = buttons[0]['id']
        with self.assertRaises(ValueError):
            deck.validate_config(config)

    def test_empty_pages_are_valid(self):
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.json')
        config['profiles']['hoved']['pages']['empty'] = []
        deck.validate_config(config)

    def test_malformed_import_fields_are_rejected_cleanly(self):
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.json')
        config['profiles']['hoved']['match'] = [42]
        with self.assertRaisesRegex(ValueError, 'match'):
            deck.validate_config(config)
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.json')
        config['profiles']['hoved']['pages']['hoved'][0]['actions'] = [{'type': 'delay', 'ms': '500'}]
        with self.assertRaisesRegex(ValueError, 'delay'):
            deck.validate_config(config)
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.json')
        config['triggers'] = 'not-a-list'
        with self.assertRaisesRegex(ValueError, 'triggers'):
            deck.validate_config(config)

    def test_unicode_labels_match_the_firmware_byte_limit(self):
        daemon = self.daemon()
        daemon.config['profiles']['hoved']['pages']['hoved'][0]['label'] = 'ø' * 20
        label = daemon.current_buttons()[0]['label']
        self.assertEqual(label, 'ø' * 12)

    def test_folder_and_back_restore_previous_page(self):
        daemon = self.daemon()
        daemon.panel.push_buttons = Mock()
        daemon.panel.send_line = Mock()
        daemon.switch_page('system', folder=True)
        self.assertEqual((daemon.page, daemon.folder_stack), ('system', ['hoved']))
        daemon.run_action({'type': 'back'})
        self.assertEqual((daemon.page, daemon.folder_stack), ('hoved', []))

    def test_pinned_button_overrides_same_slot_on_every_page(self):
        daemon = self.daemon()
        daemon.config['profiles']['hoved']['pinned'] = [
            {'id': 18, 'label': 'Fast', 'icon': 'home', 'color': '#35D07F', 'actions': []}]
        daemon.page = 'system'
        button = next(item for item in daemon.current_buttons() if item['id'] == 18)
        self.assertEqual(button['label'], 'Fast')

    def test_toggle_advances_only_after_success(self):
        daemon = self.daemon()
        button = daemon.config['profiles']['hoved']['pages']['hoved'][0]
        button['actions'] = []
        button['states'] = [{'label': 'Av'}, {'label': 'På'}]
        self.assertTrue(daemon.dispatch_press(button['id']))
        self.assertEqual(daemon.current_buttons()[0]['label'], 'På')
        button['actions'] = [{'type': 'shell', 'command': 'synthetic'}]
        with patch.object(deck.subprocess, 'run', return_value=types.SimpleNamespace(returncode=1)):
            self.assertFalse(daemon.dispatch_press(button['id']))
        self.assertEqual(daemon.current_buttons()[0]['label'], 'På')

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
            with self.assertRaisesRegex(ValueError, 'kunne ikke leses'):
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
        daemon.config['profiles']['hoved']['pages']['hoved'][0]['actions'] = [{'type': 'press', 'id': 1}]
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
        daemon.profile = 'koding'
        daemon.auto_profile = 'koding'
        context = {'exe': 'notepad.exe', 'title': 'Notepad', 'processes': ['notepad.exe']}
        with patch.object(deck, 'foreground_context', return_value=context):
            daemon.focus_tick()
        self.assertEqual(daemon.jobs.get_nowait(), ('profile', 'hoved'))

    def test_manual_home_is_not_immediately_overridden_by_focus(self):
        daemon = self.daemon()
        daemon.args.no_focus = False
        daemon.foreground = {'exe': 'chatgpt.exe', 'title': 'ChatGPT', 'processes': ['chatgpt.exe']}
        daemon.config['profiles']['koding']['match'] = ['chatgpt.exe']
        daemon.switch_profile('hoved')
        with patch.object(deck, 'foreground_context', return_value=daemon.foreground):
            daemon.focus_tick()
        self.assertTrue(daemon.jobs.empty())
        changed = {'exe': 'notepad.exe', 'title': 'Notepad', 'processes': ['notepad.exe']}
        with patch.object(deck, 'foreground_context', return_value=changed):
            daemon.focus_tick()
        self.assertEqual(daemon.manual_focus_exe, '')

    def test_home_returns_to_default_first_page(self):
        daemon = self.daemon()
        daemon.profile = 'hoved'
        daemon.page = 'system'
        daemon.folder_stack = ['hoved']
        daemon.run_action({'type': 'home'})
        self.assertEqual((daemon.profile, daemon.page, daemon.folder_stack), ('hoved', 'hoved', []))
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
        daemon.config['profiles']['koding']['match'] = ['process:claude.exe']
        context = {'exe': 'windowsterminal.exe', 'title': 'Terminal',
                   'processes': ['windowsterminal.exe', 'claude.exe']}
        with patch.object(deck, 'foreground_context', return_value=context):
            daemon.focus_tick()
        self.assertEqual(daemon.jobs.get_nowait(), ('profile', 'koding'))

    def test_agent_status_variables_follow_running_processes(self):
        daemon = self.daemon()
        processes = [types.SimpleNamespace(info={'name': 'claude.exe'}),
                     types.SimpleNamespace(info={'name': 'ZCode.exe'})]
        with patch.object(deck.psutil, 'process_iter', return_value=processes):
            daemon.agent_tick(1)
        self.assertEqual(daemon.agents, {'codex': False, 'claude': True, 'zcode': True})
        self.assertEqual(daemon.substitute('Claude $(agent:claude)'), 'Claude PÅ')

    def test_invalid_profile_reload_preserves_accepted_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profiles.json'
            original = (ROOT / 'host/profiles.json').read_text(encoding='utf-8')
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
            path.write_text((ROOT / 'host/profiles.json').read_text(encoding='utf-8'), encoding='utf-8')
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
            launcher.cmdline.return_value = ['python.exe', str(ROOT / 'host/agent_deckd.py')]
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
            process = Mock()
            process.create_time.return_value = 200
            process.cmdline.return_value = ['python.exe', str(ROOT / 'host/agent_deckd.py')]
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
                'port': 'COM4', 'profile': 'hoved', 'page': 'apper', 'buttons': 8,
                'last_action': {'id': 2, 'label': 'ChatGPT', 'ok': True, 'at': 10}}))
            status = controller.status()
            self.assertTrue(status['device']['connected'])
            self.assertEqual((status['device']['profile'], status['device']['page']), ('hoved', 'apper'))
            self.assertEqual(status['device']['last_action']['label'], 'ChatGPT')

    def test_controller_rejects_stale_runtime_status(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller()
            controller.runtime_path = Path(directory) / 'runtime.json'
            controller.processes = Mock(return_value=[Mock(pid=77)])
            controller.runtime_path.write_text(json.dumps({'pid': 77, 'updated': 1, 'connected': True}))
            self.assertFalse(controller.status()['device']['connected'])

    def test_windows_autostart_script_can_be_enabled_and_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('deck_control.os.name', 'nt'):
                path = set_autostart(True, directory)
                self.assertTrue(autostart_enabled(directory))
                self.assertIn('start_host.py', path.read_text(encoding='utf-8'))
                self.assertIn('pythonw.exe', path.read_text(encoding='utf-8'))
                set_autostart(False, directory)
                self.assertFalse(autostart_enabled(directory))


if __name__ == '__main__':
    unittest.main()
