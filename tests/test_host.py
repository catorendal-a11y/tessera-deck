import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck
import win_input
from system_stats import select_hwinfo_metrics
from deck_assets import Assets
from host_support import HostCase, test_daemon


class HostTests(HostCase):
    def test_default_profiles_validate_on_all_platforms(self):
        deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')

    def test_default_home_is_a_lean_starter_set_without_personal_apps(self):
        config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        profile = config['profiles']['main']
        home = profile['pages']['main']
        labels = {button['label'] for button in home}
        self.assertEqual({'Mute', 'Volume -', 'Volume +', 'Play / pause', 'Explorer', 'Terminal', 'Screenshot',
                          'Calculator', 'Show desktop', 'Lock PC', 'Status', 'Desktop', 'Audio', 'Tools'}, labels)
        self.assertNotIn('apps', profile['pages'])
        # a new owner has none of the original author's apps, so no starter key opens a program by full path
        targets = [a.get('target', '') for b in home for a in b.get('actions', [])]
        self.assertFalse([t for t in targets if '\\' in t or '%' in t])
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
        self.assertEqual(button['gauge'], {'p': 84, 't': '84C', 'b': 'lc:e186'})
        self.assertEqual(button['color'], '#FFB74D')
        daemon.stats.raw.pop('cpu_temp')
        missing = next(item for item in daemon.current_buttons() if item['id'] == 3)
        self.assertEqual(missing['gauge'], {'p': 0, 't': '--', 'b': 'lc:e186'})

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
        with patch.object(win_input, '_key') as key:
            key.side_effect = [None, OSError('blocked'), None]
            with self.assertRaises(OSError):
                deck.send_hotkey('ctrl+c')
            self.assertEqual(key.call_args_list[-1].kwargs, {'vk': 0x11, 'flags': 2})

    def test_unicode_sends_utf16_surrogates(self):
        with patch.object(win_input, '_key') as key:
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
        panel.log, panel.write_lock = Mock(), threading.RLock()
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

    def test_only_an_icon_only_key_may_go_without_a_name(self):
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
        button = config['profiles']['main']['pages']['main'][0]
        button['label'] = ''
        with self.assertRaisesRegex(ValueError, 'name'):
            deck.validate_config(config)
        button['title'] = {'position': 'hidden'}
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

    def test_a_wide_pinned_key_may_not_cover_a_page_key(self):
        config = deck.Daemon.load_profiles(ROOT / 'host/profiles.default.json')
        profile = config['profiles']['main']
        page = next(iter(profile['pages']))
        profile['pages'] = dict.fromkeys(profile['pages'], [])
        profile['pages'][page] = [{'id': 2, 'label': 'Page key'}]
        profile['pinned'] = [{'id': 1, 'label': 'Wide', 'span': 2}]
        with self.assertRaises(ValueError):
            deck.validate_config(config)
        profile['pinned'] = [{'id': 2, 'label': 'Pinned wins', 'span': 2}]
        deck.validate_config(config)

    def test_hot_reload_survives_wrongly_typed_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profiles.json'
            config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
            path.write_text(json.dumps(config), encoding='utf-8')
            daemon = test_daemon(path)
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
        with patch.object(win_input, '_key', lambda vk=0, scan=0, flags=0: sent.append((vk, flags))):
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

    def test_heal_keeps_a_missing_image_id_it_cannot_rebuild(self):
        # The editor saves the healed config: turning the id into 'ok' would lose the image for good.
        with tempfile.TemporaryDirectory() as directory:
            assets = Assets(Path(directory) / 'profiles.json')
            button = {'id': 1, 'label': 'X', 'icon': 'im:aaaaaaaaaaaa', 'actions': []}
            self.assertEqual(assets.heal({'b': [button]})['b'][0]['icon'], 'im:aaaaaaaaaaaa')
            self.assertEqual(assets.icon_for(button), 'ok')  # the daemon still shows the default icon

    def test_display_settings_default_and_validate(self):
        daemon = self.daemon()
        self.assertEqual(daemon.display_settings(), {'brightness': 100, 'dim_after': 300, 'dim_level': 10, 'night': None})
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
        daemon.dispatch_press.assert_called_once_with(1, hold=False, double=False)

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
        daemon.config['display'] = {'clock': '24h'}
        with patch.object(deck.time, 'strftime', return_value='2026-10-20T14:05:33'):
            daemon.heartbeat(daemon.panel, 1000.0)
            daemon.heartbeat(daemon.panel, 1001.0)
            daemon.heartbeat(daemon.panel, 1000.0 + deck.CLOCK_INTERVAL)
            daemon.config['display'] = {'clock': '12h'}  # a new format is sent at the next beat
            daemon.heartbeat(daemon.panel, 1002.0 + deck.CLOCK_INTERVAL)
        sent = [call.args[0] for call in daemon.panel.send_line.call_args_list]
        self.assertEqual(sent, ['AD_PING', 'AD_TIME 2026-10-20T14:05:33 24h', 'AD_PING',
                                'AD_PING', 'AD_TIME 2026-10-20T14:05:33 24h', 'AD_PING', 'AD_TIME 2026-10-20T14:05:33 12h'])

    def test_the_clock_format_follows_windows_unless_it_is_set(self):
        import daemon_display
        daemon = self.daemon()
        daemon.config['display'] = {}
        with patch.object(daemon_display, 'windows_clock', return_value='12h'):
            self.assertEqual(daemon.clock_format(), '12h')
            daemon.config['display'] = {'clock': '24h'}
            self.assertEqual(daemon.clock_format(), '24h')
        self.assertIn(daemon_display.windows_clock(), ('12h', '24h'))
        config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        config['display'] = {'clock': '12h'}
        deck.validate_config(config)
        config['display'] = {'clock': 'am/pm'}
        with self.assertRaises(ValueError):
            deck.validate_config(config)

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
        self.assertEqual((clock['p'], clock['t'], clock['color']), (85, '4.7GHz', '#35D07F'))
        idle = gauge_state({'key': 'gpu_idle', 'max': 2600, 'fmt': 'ghz'}, {'gpu_idle': 313.0}, '#B388FF')
        self.assertEqual(idle['t'], '313MHz')
        vram = gauge_state({'key': 'vram_used_gb', 'percent_key': 'vram', 'max': 100, 'fmt': 'gb', 'warn': 85, 'critical': 95}, raw, '#B388FF')
        self.assertEqual((vram['p'], vram['t'], vram['color']), (90, '14.4GB', '#FFB74D'))
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
        for bad in ({'key': ''}, {'key': 'x', 'max': 0}, {'key': 'x', 'max': float('nan')}, {'key': 'x', 'max': 1e-300, 'scale': 'log'},
                    {'key': 'x', 'warn': float('inf')}, {'key': 'x', 'critical': float('nan')}, {'key': 'x', 'fmt': 'hex'}, {'key': 'x', 'unit': 'toolong'}, 'cpu'):
            with self.subTest(bad):
                button['gauge'] = bad
                with self.assertRaises(ValueError):
                    deck.validate_config(daemon.config)

    @unittest.skipIf(importlib.util.find_spec('pystray') is None, 'pystray is not installed')
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

    @unittest.skipIf(importlib.util.find_spec('pystray') is None, 'pystray is not installed')
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

    @unittest.skipIf(importlib.util.find_spec('pystray') is None, 'pystray is not installed')
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


if __name__ == '__main__':
    unittest.main()
