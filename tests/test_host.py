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
import tesserad as deck
from system_stats import SystemStats, select_hwinfo_metrics
from deck_assets import Assets
from deck_control import Controller, autostart_enabled, set_autostart


def args(path=ROOT / 'host/profiles.default.json'):
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
        deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')

    def test_default_home_is_a_complete_app_launcher(self):
        config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        profile = config['profiles']['main']
        home = profile['pages']['main']
        labels = {button['label'] for button in home}
        self.assertEqual(len(home), 17)
        self.assertTrue({'Chrome', 'ChatGPT', 'ZCode', 'Claude', 'VS Code',
                         'GitHub Desktop', 'Terminal', 'Explorer', 'Discord',
                         'Obsidian', 'LM Studio', 'Steam'} <= labels)
        self.assertEqual({'Status', 'Desktop', 'Audio', 'Tools', 'Apps'}, labels - {
            'Chrome', 'ChatGPT', 'ZCode', 'Claude', 'VS Code', 'GitHub Desktop', 'Terminal', 'Explorer',
            'Discord', 'Obsidian', 'LM Studio', 'Steam'})
        self.assertEqual(profile['pinned'][0]['id'], 18)

    def test_every_subpage_has_back_in_slot_17_and_home_is_pinned_everywhere(self):
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
        for name, profile in config['profiles'].items():
            self.assertEqual([item['label'] for item in profile['pinned']], ['Home'], name)
            for page, buttons in profile['pages'].items():
                if page == 'main':
                    continue
                slot = next((item for item in buttons if item['id'] == 17), None)
                self.assertEqual(slot['actions'], [{'type': 'back'}], f'{name}/{page}')
                self.assertNotIn(18, [item['id'] for item in buttons], f'{name}/{page}')

    def test_every_folder_and_page_target_exists_and_ai_pages_have_no_hidden_slot(self):
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
        for name, profile in config['profiles'].items():
            for page, buttons in profile['pages'].items():
                self.assertLessEqual(max(item['id'] for item in buttons), 17, f'{name}/{page} hides slot 18')

    def test_status_page_has_full_live_dashboard(self):
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
        status = config['profiles']['main']['pages']['status']
        self.assertEqual(len(status), 17)
        labels = {item['label'] for item in status}
        for caption in ('CPU TEMP', 'CPU LOAD', 'GPU TEMP', 'GPU LOAD', 'VRAM', 'RAM', 'SENSORS', 'Back'):
            self.assertIn(caption, labels)
        self.assertTrue(all('gauge' in item for item in status if item['id'] < 17))

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
        daemon.stats.raw['cpu_temp'] = 84
        button = next(item for item in daemon.current_buttons() if item['id'] == 3)
        self.assertEqual(button['label'], 'CPU TEMP')
        self.assertEqual(button['gauge'], {'p': 84, 't': '84C'})
        self.assertEqual(button['color'], '#FFB74D')
        daemon.stats.raw.pop('cpu_temp')
        missing = next(item for item in daemon.current_buttons() if item['id'] == 3)
        self.assertEqual(missing['gauge'], {'p': 0, 't': '--'})

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
        raw = '{"type":"deck_event","button":1,"label":"Café"}\n'.encode()
        split = raw.index('é'.encode()) + 1
        panel.ser.read.side_effect = [raw[:split], raw[split:] + b'AD_PRESS OK\n']
        self.assertEqual(panel.read_lines(), [])
        lines = panel.read_lines()
        self.assertEqual(json.loads(lines[0])['label'], 'Café')
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
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
        buttons = config['profiles']['main']['pages']['main']
        buttons[1]['id'] = buttons[0]['id']
        with self.assertRaises(ValueError):
            deck.validate_config(config)

    def test_empty_pages_are_valid(self):
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
        config['profiles']['main']['pages']['empty'] = []
        deck.validate_config(config)

    def test_malformed_import_fields_are_rejected_cleanly(self):
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
        config['profiles']['main']['match'] = [42]
        with self.assertRaisesRegex(ValueError, 'match'):
            deck.validate_config(config)
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
        config['profiles']['main']['pages']['main'][0]['actions'] = [{'type': 'delay', 'ms': '500'}]
        with self.assertRaisesRegex(ValueError, 'delay'):
            deck.validate_config(config)
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
        config['triggers'] = 'not-a-list'
        with self.assertRaisesRegex(ValueError, 'triggers'):
            deck.validate_config(config)

    def test_wrongly_typed_config_values_raise_value_error(self):
        def first_button(config):
            return config['profiles']['main']['pages']['main'][0]
        mutations = {
            'color': lambda c: first_button(c).update(color=5),
            'state color': lambda c: first_button(c).update(states=[{'color': 1}, {'color': 2}]),
            'trigger when': lambda c: c.update(triggers=[{'when': [1], 'actions': []}]),
            'daily at': lambda c: c.update(triggers=[{'when': {'type': 'daily', 'at': 5}, 'actions': []}]),
            'http body': lambda c: first_button(c).update(actions=[{'type': 'http', 'url': 'x', 'body': 5}]),
        }
        for name, mutate in mutations.items():
            with self.subTest(name):
                config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
                mutate(config)
                with self.assertRaises(ValueError):
                    deck.validate_config(config)

    def test_hot_reload_survives_wrongly_typed_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profiles.json'
            config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
            path.write_text(json.dumps(config), encoding='utf-8')
            daemon = deck.Daemon(args(path))
            daemon.log = Mock()
            config['profiles']['main']['pages']['main'][0]['color'] = 5
            path.write_text(json.dumps(config), encoding='utf-8')
            daemon.profile_stamp = 0
            daemon.reload_profiles()
            self.assertIn('main', daemon.config['profiles'])
            self.assertTrue(daemon.log.called)

    def test_punctuation_numpad_and_navigation_hotkeys_parse(self):
        for combo in ('ctrl+minus', 'ctrl+equals', 'win+printscreen', 'alt+numpad5', 'shift+insert'):
            with self.subTest(combo):
                self.assertTrue(deck.dry_hotkey(combo)[0])

    def test_navigation_keys_are_sent_as_extended_keys(self):
        sent = []
        with patch.object(deck, '_key', lambda vk=0, scan=0, flags=0: sent.append((vk, flags))):
            deck.send_hotkey('ctrl+left')
        self.assertEqual(sent, [(0x11, 0), (37, 1), (37, 3), (0x11, 2)])

    def test_triggers_may_target_pages_of_any_profile(self):
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
        config['profiles']['andre'] = {'pages': {'ekstra': []}}
        config['triggers'] = [{'when': {'type': 'startup'},
                               'actions': [{'type': 'page', 'page': 'ekstra'}]}]
        deck.validate_config(config)
        config['triggers'][0]['actions'][0]['page'] = 'does-not-exist'
        with self.assertRaises(ValueError):
            deck.validate_config(config)

    def test_read_lines_splits_multiple_frames_and_keeps_partial_tail(self):
        panel = deck.PanelSerial.__new__(deck.PanelSerial)
        panel.rx = bytearray()
        panel.ser = Mock(in_waiting=0)
        lf, crlf = bytes([10]), bytes([13, 10])
        panel.ser.read.return_value = b'one' + lf + b'two' + crlf + b'par'
        self.assertEqual(panel.read_lines(), ['one', 'two'])
        panel.ser.read.return_value = b'tial' + lf
        self.assertEqual(panel.read_lines(), ['partial'])

    def test_app_icon_and_missing_images_resolve_from_the_open_action(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = Assets(Path(directory) / 'profiles.json')
            assets.rebuild_from_actions = Mock(return_value='im:0123456789ab')
            opener = [{'type': 'open', 'target': 'chrome.exe'}]
            self.assertEqual(assets.icon_for({'icon': 'app', 'actions': opener}), 'im:0123456789ab')
            self.assertEqual(assets.icon_for({'icon': 'im:aaaaaaaaaaaa', 'actions': opener}), 'im:0123456789ab')
            self.assertEqual(assets.icon_for({'icon': 'app', 'actions': opener}), 'im:0123456789ab')
            self.assertEqual(assets.rebuild_from_actions.call_count, 2)

    def test_unresolvable_app_icon_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = Assets(Path(directory) / 'profiles.json')
            assets.rebuild_from_actions = Mock(return_value=None)
            self.assertEqual(assets.icon_for({'icon': 'app', 'actions': []}), 'ok')
            self.assertEqual(assets.icon_for({'icon': 'im:bbbbbbbbbbbb'}), 'ok')

    def test_named_icons_and_existing_images_are_left_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = Assets(Path(directory) / 'profiles.json')
            assets.rebuild_from_actions = Mock()
            assets.root.mkdir()
            (assets.root / 'cccccccccccc.adimg').write_bytes(b'ADI1')
            self.assertEqual(assets.icon_for({'icon': 'im:cccccccccccc'}), 'im:cccccccccccc')
            self.assertEqual(assets.icon_for({'icon': 'bolt'}), 'bolt')
            assets.rebuild_from_actions.assert_not_called()

    def test_daemon_uses_the_shared_icon_resolver(self):
        daemon = self.daemon()
        daemon.assets = Mock()
        daemon.assets.icon_for.return_value = 'im:0123456789ab'
        self.assertEqual(daemon.resolve_icon({'icon': 'app'}), 'im:0123456789ab')

    def test_program_targets_resolve_aliases_and_variables(self):
        from deck_assets import resolve_program_target
        self.assertIn('WindowsTerminal', resolve_program_target('wt.exe'))
        self.assertEqual(resolve_program_target('shell:AppsFolder' + chr(92) + 'X!App'),
                         'shell:AppsFolder' + chr(92) + 'X!App')
        with patch.dict('os.environ', {'DECK_TEST_DIR': 'C:' + chr(92) + 'Apps'}):
            self.assertEqual(resolve_program_target('%DECK_TEST_DIR%' + chr(92) + 'a.exe'),
                             'C:' + chr(92) + 'Apps' + chr(92) + 'a.exe')
        with self.assertRaises(ValueError):
            resolve_program_target('  ')

    @unittest.skipUnless(sys.platform == 'win32', 'shell icons need Windows')
    def test_program_icon_is_extracted_from_the_shell_at_full_quality(self):
        from deck_assets import shell_item_image
        image = shell_item_image('C:' + chr(92) + 'Windows' + chr(92) + 'explorer.exe')
        self.assertGreaterEqual(image.width, 128)
        self.assertGreater(image.getchannel('A').getextrema()[1], 0)
        with tempfile.TemporaryDirectory() as directory:
            result = Assets(Path(directory) / 'profiles.json').import_program_icon('explorer.exe')
            self.assertRegex(result['id'], r'^im:[0-9a-f]{12}$')

    def test_single_instance_lock_blocks_a_second_holder_until_released(self):
        from host_runtime import InstanceLock
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'host.lock'
            first, second = InstanceLock(path), InstanceLock(path)
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()

    def test_port_follows_the_remembered_serial_number_only(self):
        from host_runtime import remember_port, resolve_port
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'device.json'
            ports = {'COM4': 'PANEL', 'COM6': 'OTHER-BOARD'}
            self.assertEqual(resolve_port('COM4', state, ports), 'COM4')
            remember_port('COM4', state, ports)
            self.assertEqual(resolve_port('COM4', state, ports), 'COM4')
            renumbered = {'COM9': 'PANEL', 'COM6': 'OTHER-BOARD'}
            self.assertEqual(resolve_port('COM4', state, renumbered), 'COM9')
            swapped = {'COM4': 'OTHER-BOARD', 'COM7': 'PANEL'}
            self.assertEqual(resolve_port('COM4', state, swapped), 'COM7')
            gone = {'COM6': 'OTHER-BOARD'}
            self.assertEqual(resolve_port('COM4', state, gone), 'COM4')

    def test_heal_rebuilds_missing_images_and_leaves_existing_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = Assets(Path(directory) / 'profiles.json')
            assets.rebuild_from_actions = Mock(return_value='im:0123456789ab')
            config = {'profiles': {'p': {'pages': {'a': [
                {'id': 1, 'label': 'X', 'icon': 'im:aaaaaaaaaaaa', 'actions': [{'type': 'open', 'target': 'x.exe'}]},
                {'id': 2, 'label': 'Y', 'icon': 'bolt', 'actions': []}]}}}}
            healed = assets.heal(config)
            buttons = healed['profiles']['p']['pages']['a']
            self.assertEqual([b['icon'] for b in buttons], ['im:0123456789ab', 'bolt'])
            self.assertEqual(config['profiles']['p']['pages']['a'][0]['icon'], 'im:aaaaaaaaaaaa')

    def test_display_settings_default_and_validate(self):
        daemon = self.daemon()
        self.assertEqual(daemon.display_settings(), {'brightness': 100, 'dim_after': 300, 'dim_level': 10})
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
        config['display'] = {'brightness': 60, 'dim_after': 300, 'dim_level': 5}
        deck.validate_config(config)
        for bad in ({'brightness': 0}, {'brightness': 101}, {'dim_after': -1}, {'dim_level': 'x'},
                    {'dim_after': True}, 'loud'):
            with self.subTest(bad):
                config['display'] = bad
                with self.assertRaises(ValueError):
                    deck.validate_config(config)

    def dynamic_label_daemon(self):
        config = {'default_profile': 'Main', 'profiles': {'Main': {'match': [], 'pages': {
            'First': [{'id': 1, 'label': 'CPU $(var:cpu)', 'actions': []},
                      {'id': 2, 'label': '$(var:claude)', 'actions': []}],
            'Second': [{'id': 1, 'label': 'Other', 'actions': []}]}}}}
        daemon = self.daemon(deck.validate_config(config))
        daemon.profile, daemon.page = 'Main', 'First'
        daemon.dispatch_press = Mock()
        return daemon

    def test_press_on_a_label_that_changed_since_the_panel_showed_it_still_runs(self):
        daemon = self.dynamic_label_daemon()
        daemon.custom_vars['cpu'] = '41'
        daemon.push_page(force=True)
        daemon.custom_vars['cpu'] = '42'
        daemon.push_page()
        daemon.custom_vars['cpu'] = '43'  # computed after the press, not yet pushed
        daemon.handle_job(('press', 1, 'CPU 41'))
        daemon.dispatch_press.assert_called_once_with(1, hold=False)

    def test_press_from_a_page_that_is_no_longer_shown_is_ignored(self):
        daemon = self.dynamic_label_daemon()
        daemon.custom_vars['cpu'] = '41'
        daemon.push_page(force=True)
        daemon.switch_page('Second')
        daemon.handle_job(('press', 1, 'CPU 41'))
        daemon.dispatch_press.assert_not_called()

    def test_a_label_that_is_only_an_unset_variable_does_not_block_the_page(self):
        daemon = self.dynamic_label_daemon()
        labels = {b['id']: b['label'] for b in daemon.current_buttons()}
        self.assertEqual(labels[2], ' ')  # the panel rejects layouts with empty labels

    def test_idle_panel_dims_once_and_press_wakes_without_firing(self):
        daemon = self.daemon()
        daemon.config['display'] = {'brightness': 80, 'dim_after': 60, 'dim_level': 7}
        daemon.last_activity = 1000.0
        daemon.idle_tick(1030.0)
        daemon.panel.send_line.assert_not_called()
        daemon.idle_tick(1061.0)
        daemon.idle_tick(1100.0)
        daemon.panel.send_line.assert_called_once_with('AD_DISPLAY_DIM 7')
        self.assertTrue(daemon.dimmed)
        daemon.dispatch_press = Mock()
        daemon.handle_job(('press', 1, None))
        daemon.dispatch_press.assert_not_called()
        self.assertFalse(daemon.dimmed)
        daemon.panel.send_line.assert_called_with('AD_DISPLAY_WAKE')
        daemon.handle_job(('press', 1, None))
        daemon.dispatch_press.assert_called_once()

    def test_touch_wake_from_the_panel_resets_idle_without_a_press(self):
        daemon = self.daemon()
        daemon.dimmed = True
        daemon.last_activity = 0.0
        panel = Mock()
        panel.read_lines.side_effect = [['{"type":"wake"}'], OSError('unplugged')]
        daemon.panel = panel
        daemon.reader_loop(panel)
        self.assertEqual(daemon.jobs.get_nowait(), ('panel-woke',))
        daemon.handle_job(('panel-woke',))
        self.assertFalse(daemon.dimmed)
        self.assertGreater(daemon.last_activity, 0.0)
        panel.send_line.assert_not_called()  # the panel already restored its backlight
        daemon.log.assert_any_call('Panel woke by touch')

    def test_heartbeat_pings_every_beat_and_sends_the_clock_every_ten_minutes(self):
        daemon = self.daemon()
        with patch.object(deck.time, 'strftime', return_value='2026-10-20T14:05:33'):
            daemon.heartbeat(daemon.panel, 1000.0)
            daemon.heartbeat(daemon.panel, 1001.0)
            daemon.heartbeat(daemon.panel, 1000.0 + deck.CLOCK_INTERVAL)
        sent = [call.args[0] for call in daemon.panel.send_line.call_args_list]
        self.assertEqual(sent, ['AD_PING', 'AD_TIME 2026-10-20T14:05:33', 'AD_PING',
                                'AD_PING', 'AD_TIME 2026-10-20T14:05:33'])

    def test_dimming_can_be_turned_off_and_page_pushes_do_not_undo_it(self):
        daemon = self.daemon()
        daemon.config['display'] = {'dim_after': 0}
        daemon.last_activity = 0.0
        daemon.idle_tick(10 ** 6)
        daemon.panel.send_line.assert_not_called()
        daemon.dimmed = True
        daemon.push_page(force=True)
        sent = [call.args[0] for call in daemon.panel.send_line.call_args_list]
        self.assertNotIn('AD_DISPLAY_WAKE', sent)

    def test_panel_dims_by_default_after_five_idle_minutes(self):
        daemon = self.daemon()
        daemon.last_activity = 100.0
        daemon.idle_tick(399.0)
        daemon.panel.send_line.assert_not_called()
        daemon.idle_tick(401.0)
        daemon.panel.send_line.assert_called_once_with('AD_DISPLAY_DIM 10')
        daemon.log.assert_any_call('Panel dimmed after 300 s without a press')

    def test_locking_windows_dims_the_panel_and_unlocking_wakes_it(self):
        daemon = self.daemon()
        daemon.lock_tick(False)
        daemon.panel.send_line.assert_not_called()
        daemon.lock_tick(True)
        daemon.panel.send_line.assert_called_once_with('AD_DISPLAY_DIM 10')
        self.assertTrue(daemon.dimmed)
        daemon.lock_tick(True)
        self.assertEqual(daemon.panel.send_line.call_count, 1)
        daemon.lock_tick(False)
        daemon.panel.send_line.assert_called_with('AD_DISPLAY_WAKE')
        self.assertFalse(daemon.dimmed)

    def test_locking_does_not_dim_when_auto_dim_is_off(self):
        daemon = self.daemon()
        daemon.config['display'] = {'dim_after': 0}
        daemon.lock_tick(True)
        daemon.panel.send_line.assert_not_called()

    def test_runtime_file_reports_whether_the_panel_is_dimmed(self):
        daemon = self.daemon()
        daemon.runtime_path = Path(tempfile.mkdtemp()) / 'runtime.json'
        daemon.publish_runtime = deck.Daemon.publish_runtime.__get__(daemon)
        daemon.dimmed = True
        daemon.publish_runtime(True, force=True)
        self.assertTrue(json.loads(daemon.runtime_path.read_text(encoding='utf-8'))['dimmed'])

    def test_brightness_is_applied_on_request(self):
        daemon = self.daemon()
        daemon.config['display'] = {'brightness': 35}
        daemon.dimmed = True
        daemon.apply_brightness()
        daemon.panel.send_line.assert_called_once_with('AD_BRIGHTNESS 35')
        self.assertFalse(daemon.dimmed)

    def test_gauge_state_scales_formats_and_colors_by_threshold(self):
        from system_stats import gauge_state, MISSING_COLOR
        raw = {'cpu_temp': 85.0, 'cpu_clock': 4677.0, 'vram': 90.0, 'vram_used_gb': 14.4, 'net_down': 1_000_000.0,
               'uptime': 4 * 86400 + 7200.0, 'sensors': 1.0}
        hot = gauge_state({'key': 'cpu_temp', 'max': 100, 'unit': 'C', 'warn': 75, 'critical': 90}, raw, '#35D07F')
        self.assertEqual((hot['p'], hot['t'], hot['color']), (85, '85C', '#FFB74D'))
        clock = gauge_state({'key': 'cpu_clock', 'max': 5500, 'fmt': 'ghz'}, raw, '#35D07F')
        self.assertEqual((clock['p'], clock['t'], clock['color']), (85, '4.7G', '#35D07F'))
        idle = gauge_state({'key': 'gpu_idle', 'max': 2600, 'fmt': 'ghz'}, {'gpu_idle': 313.0}, '#B388FF')
        self.assertEqual(idle['t'], '313M')
        vram = gauge_state({'key': 'vram_used_gb', 'percent_key': 'vram', 'max': 100, 'fmt': 'gb', 'warn': 85, 'critical': 95}, raw, '#B388FF')
        self.assertEqual((vram['p'], vram['t'], vram['color']), (90, '14.4G', '#FFB74D'))
        net = gauge_state({'key': 'net_down', 'max': 125_000_000, 'fmt': 'rate', 'scale': 'log'}, raw, '#64B5F6')
        self.assertGreater(net['p'], 50)
        self.assertEqual(gauge_state({'key': 'uptime', 'max': 604800, 'fmt': 'uptime'}, raw, '#90A4AE')['t'], '4d')
        self.assertEqual(gauge_state({'key': 'sensors', 'max': 1, 'fmt': 'live'}, raw, '#90A4AE')['t'], 'LIVE')
        missing = gauge_state({'key': 'gpu_temp', 'max': 100}, raw, '#35D07F')
        self.assertEqual(missing, {'p': 0, 't': '--', 'color': MISSING_COLOR})

    def test_gauge_buttons_reach_the_panel_with_live_values_and_validate(self):
        daemon = self.daemon()
        daemon.stats.raw = {'cpu_load': 42.0}
        button = daemon.config['profiles']['main']['pages']['main'][0]
        button['gauge'] = {'key': 'cpu_load', 'max': 100, 'unit': '%', 'warn': 80}
        deck.validate_config(daemon.config)
        first = daemon.current_buttons()[0]
        self.assertEqual(first['gauge'], {'p': 42, 't': '42%'})
        for bad in ({'key': ''}, {'key': 'x', 'max': 0}, {'key': 'x', 'fmt': 'hex'}, {'key': 'x', 'unit': 'toolong'}, 'cpu'):
            with self.subTest(bad):
                button['gauge'] = bad
                with self.assertRaises(ValueError):
                    deck.validate_config(daemon.config)

    def test_tray_state_text_and_profile_commands(self):
        import tessera_tray as tray
        self.assertEqual(tray.tray_state({}), 'stopped')
        self.assertEqual(tray.tray_state({'running': True, 'device': {'connected': False}}), 'waiting')
        connected = {'running': True, 'device': {'connected': True, 'port': 'COM4', 'profile': 'main', 'page': 'audio'}}
        self.assertEqual(tray.tray_state(connected), 'connected')
        self.assertEqual(tray.status_text(connected), 'Connected · COM4 · main / audio')
        self.assertEqual(tray.status_text({}), 'Host stopped')
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
        self.assertEqual(tray.command_for_profile(config, 'coding'), {'profile': 'coding', 'page': 'main'})

    def test_tray_writes_commands_atomically_and_persists_brightness(self):
        import tessera_tray as tray
        with tempfile.TemporaryDirectory() as directory:
            command = Path(directory) / 'command.json'
            tray.write_command({'profile': 'main', 'page': 'status'}, command)
            self.assertEqual(json.loads(command.read_text(encoding='utf-8')), {'profile': 'main', 'page': 'status'})
            self.assertFalse(command.with_suffix('.tmp').exists())
            profiles = Path(directory) / 'profiles.json'
            profiles.write_text((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'), encoding='utf-8')
            tray.set_brightness(40, profiles)
            self.assertEqual(json.loads(profiles.read_text(encoding='utf-8'))['display']['brightness'], 40)

    def test_tray_icon_is_a_nine_tile_mosaic_whose_top_right_tile_shows_the_status(self):
        import tessera_tray as tray
        for size in (16, 20, 24, 32, 48, 64):
            tiles = tray.icon_tiles(size)
            self.assertEqual(len(tiles), 9)
            self.assertTrue(all(edge >= 3 for _x, _y, edge in tiles), f'tiles too small at {size}px')
            self.assertTrue(all(x >= 1 and y >= 1 and x + edge <= size - 1 and y + edge <= size - 1
                                for x, y, edge in tiles), f'tiles leave the icon at {size}px')
            for state, color in tray.STATE_COLORS.items():
                icon = tray.make_icon(state, size)
                self.assertEqual(icon.size, (size, size))
                centers = [icon.getpixel((x + edge // 2, y + edge // 2))[:3] for x, y, edge in tiles]
                expected = [color if tile is None else tile for tile in tray.TILE_COLORS]
                self.assertEqual(centers, expected, f'{state} at {size}px')

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
            self.assertEqual(published['gauges']['1'], {'p': 42, 't': '42%', 'color': '#35D07F'})
            self.assertEqual(published['gauges']['3']['color'], '#FF7070')
            self.assertEqual(published['gauges']['7'], {'p': 0, 't': '--', 'color': '#4A5A63'})
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
        daemon.enqueue = Mock()
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
        daemon.enqueue.assert_called_with(('var', 'claude', 'working'))
        self.api_call(info, 'POST', '/v1/press', {'button': 3})
        daemon.enqueue.assert_called_with(('api-press', 3))
        self.api_call(info, 'POST', '/v1/state', {'button': 2, 'state': 1})
        daemon.enqueue.assert_called_with(('state', 2, 1))
        self.api_call(info, 'POST', '/v1/feedback', {'button': 4, 'ok': False})
        daemon.enqueue.assert_called_with(('feedback', 4, False))
        self.api_call(info, 'POST', '/v1/display', {'action': 'dim'})
        daemon.enqueue.assert_called_with(('dim',))
        self.api_call(info, 'POST', '/v1/page', {'profile': 'coding', 'page': 'git'})
        daemon.enqueue.assert_any_call(('profile', 'coding'))
        daemon.enqueue.assert_called_with(('page', 'git'))

    def test_control_api_rejects_bad_input_and_unauthorised_callers(self):
        daemon, server, info = self.api_server()
        for path, body in (('/v1/var', {'name': 'bad name'}), ('/v1/var', {'name': 'x', 'value': 'v' * 201}),
                           ('/v1/press', {'button': 0}), ('/v1/press', {'button': '3'}),
                           ('/v1/state', {'button': 2, 'state': 8}), ('/v1/feedback', {'button': 2, 'ok': 'yes'}),
                           ('/v1/display', {'action': 'explode'}), ('/v1/page', {'profile': 'nope'}),
                           ('/v1/page', {'page': 'nope'}), ('/v1/nothing', {})):
            with self.subTest(path=path, body=body):
                self.assertIn(self.api_call(info, 'POST', path, body)[0], (400, 404))
        daemon.enqueue.assert_not_called()
        self.assertEqual(self.api_call(info, 'POST', '/v1/press', {'button': 1}, {'X-Deck-Token': 'wrong'})[0], 401)
        self.assertEqual(self.api_call(info, 'POST', '/v1/press', {'button': 1}, {'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.api_call(info, 'POST', '/v1/press', {'button': 1}, {'Host': 'evil.example'})[0], 403)
        daemon.enqueue.assert_not_called()

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
        daemon.enqueue.assert_called_with(('var', 'claude', 'waiting'))
        self.assertEqual(deckctl.main(['state', '3', '2'], info), 0)
        daemon.enqueue.assert_called_with(('state', 3, 1))
        self.assertEqual(deckctl.main(['alert', '5'], info), 0)
        daemon.enqueue.assert_called_with(('feedback', 5, False))
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
        self.assertEqual(daemon.jobs.get_nowait(), ('profile', 'main'))

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
        self.assertEqual(daemon.jobs.get_nowait(), ('profile', 'coding'))
        daemon.profile = 'coding'
        with patch.object(deck, 'foreground_context',
                          return_value={'exe': 'notepad.exe', 'title': 'Notepad', 'processes': ['notepad.exe']}):
            daemon.focus_tick()
        self.assertEqual(daemon.jobs.get_nowait(), ('profile', 'Codex'))
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
        self.assertEqual(daemon.jobs.get_nowait(), ('profile', 'coding'))

    def test_agent_status_variables_follow_running_processes(self):
        daemon = self.daemon()
        processes = [types.SimpleNamespace(info={'name': 'claude.exe'}),
                     types.SimpleNamespace(info={'name': 'ZCode.exe'})]
        with patch.object(deck.psutil, 'process_iter', return_value=processes):
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
            process = Mock()
            process.create_time.return_value = 200
            process.cmdline.return_value = ['python.exe', str(ROOT / 'host/tesserad.py')]
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
            with patch('deck_control.os.name', 'nt'):
                path = set_autostart(True, directory)
                self.assertTrue(autostart_enabled(directory))
                self.assertIn('tessera_tray.py', path.read_text(encoding='utf-8'))
                self.assertIn('pythonw.exe', path.read_text(encoding='utf-8'))
                set_autostart(False, directory)
                self.assertFalse(autostart_enabled(directory))


if __name__ == '__main__':
    unittest.main()
