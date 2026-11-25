"""The cockpit screens of a protocol 4 panel: what the host sends and what a touch on them does."""
import itertools
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
import unittest.mock
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import cockpit
import tesserad as deck
import host_support
from host_support import HostCase


class PayloadTests(unittest.TestCase):
    def test_an_agent_gets_a_lane_when_it_runs_or_has_reported_a_state(self):
        variables = {'claude': 'waiting', 'claude.message': 'Wants to run: npm test', 'claude.project': 'tessera',
                     'codex': 'ended'}
        lanes = json.loads(cockpit.agents_payload(variables, {'claude': False, 'codex': False, 'zcode': True}))['agents']
        self.assertEqual([lane['id'] for lane in lanes], ['claude', 'zcode'])
        self.assertEqual((lanes[0]['state'], lanes[0]['text'], lanes[0]['sub']), ('waiting', 'Wants to run: npm test', 'tessera'))
        self.assertEqual(lanes[1]['state'], 'idle')

    def test_a_working_agent_without_a_message_names_its_tool(self):
        lanes = json.loads(cockpit.agents_payload({'claude': 'working', 'claude.tool': 'Bash'}, {}))['agents']
        self.assertEqual(lanes[0]['text'], 'Using Bash')

    def test_a_busy_agent_says_since_when_and_an_idle_one_does_not(self):
        since = {'claude': '14:05', 'codex': '13:10'}
        lanes = json.loads(cockpit.agents_payload({'claude': 'working', 'codex': 'idle'}, {'codex': True}, since=since))['agents']
        self.assertEqual({lane['id']: lane.get('at') for lane in lanes}, {'claude': '14:05', 'codex': None})

    def test_the_longest_line_with_its_command_word_fits_the_panels_buffer(self):
        # main.cpp reads a line into char line[1100]: 1099 characters, or the panel drops it.
        self.assertLess(len('AD_AGENTS ') + cockpit.MAX_LINE + len('\n'), 1100)

    def test_every_line_fits_the_panels_buffer_even_with_long_foreign_text(self):
        variables = {key: 'working' for key, _, _ in cockpit.AGENTS}
        variables.update({f'{key}.message': 'æøå' * 200 for key, _, _ in cockpit.AGENTS})
        self.assertLessEqual(len(cockpit.agents_payload(variables, {})), cockpit.MAX_LINE)
        display = {key: '100' for _, key, *_ in cockpit.STATS}
        self.assertLessEqual(len(cockpit.stats_payload(display, {})), cockpit.MAX_LINE)

    def test_a_reading_over_its_limit_is_marked_and_a_missing_sensor_shows_dashes(self):
        stats = json.loads(cockpit.stats_payload({'disk': '93', 'cpu_load': '4'}, {'disk': 93.0, 'cpu_load': 4.2}))['stats']
        by_name = {stat['name']: stat for stat in stats}
        self.assertTrue(by_name['Disk']['warn'])
        self.assertEqual((by_name['Disk']['p'], by_name['CPU load']['p']), (93, 4))
        self.assertNotIn('warn', by_name['CPU load'])  # the panel reads a missing warn as false
        self.assertEqual((by_name['GPU temp']['value'], by_name['GPU temp']['p']), ('--', 0))
        self.assertEqual(len(stats), 8)

    def test_twelve_readings_fit_one_line_whichever_twelve_are_chosen(self):
        display = {key: '1234567' for key in cockpit.STAT_IDS}  # seven characters, the longest value the panel gets
        raw = {key: 10.0 ** 12 for key in cockpit.STAT_IDS}  # every bar full, every reading with a limit over it
        for chosen in itertools.combinations(cockpit.STAT_IDS, 12):
            line = cockpit.stats_payload(display, raw, list(chosen), limit=12)
            self.assertLessEqual(len(line), cockpit.MAX_LINE, chosen)
            self.assertEqual(len(json.loads(line)['stats']), 12, chosen)

    def test_a_line_that_would_be_too_long_loses_readings_from_the_end(self):
        display = {key: 'æøåæøåæ' for key in cockpit.STAT_IDS}  # each letter is sent as six characters
        line = cockpit.stats_payload(display, {}, list(cockpit.STAT_IDS), limit=12)
        self.assertLessEqual(len(line), cockpit.MAX_LINE)
        names = [stat['name'] for stat in json.loads(line)['stats']]
        self.assertTrue(0 < len(names) < 12)
        self.assertEqual(names, [label for label, *_ in cockpit.STATS][:len(names)])

    def test_the_panel_says_how_many_readings_it_shows_and_an_older_one_shows_eight(self):
        self.assertEqual(cockpit.stats_limit({'statsMax': 12}), 12)
        self.assertEqual(cockpit.stats_limit({'statsMax': 10}), 10)
        for info in ({}, {'statsMax': 0}, {'statsMax': True}, {'statsMax': '12'}, {'statsMax': None}):
            self.assertEqual(cockpit.stats_limit(info), 8, info)
        self.assertEqual(cockpit.stats_limit({'statsMax': 40}), cockpit.MAX_STATS)  # the host knows no more than that

    def test_the_limit_matches_the_firmware(self):
        root = Path(__file__).resolve().parents[1]
        header = (root / 'main/deck_model.h').read_text(encoding='utf-8')
        self.assertEqual(re.search(r'#define DECK_STATS_MAX (\d+)', header).group(1), str(cockpit.MAX_STATS))
        self.assertIn('"statsMax",DECK_STATS_MAX', (root / 'main/main.cpp').read_text(encoding='utf-8'))

    def test_a_program_name_becomes_a_short_title(self):
        self.assertEqual(cockpit.app_title('spotify.exe'), 'Spotify')
        self.assertEqual(len(cockpit.app_title('Godot_v4.7.2-stable_win64.exe')), 15)


class PanelChoiceTests(unittest.TestCase):
    def test_the_chosen_agents_and_readings_are_all_that_is_sent(self):
        variables = {'claude': 'working', 'codex': 'working'}
        lanes = json.loads(cockpit.agents_payload(variables, {}, None, ['codex']))['agents']
        self.assertEqual([lane['id'] for lane in lanes], ['codex'])
        stats = json.loads(cockpit.stats_payload({'ram': '55'}, {'ram': 55.0}, ['ram', 'net_down']))['stats']
        self.assertEqual([stat['name'] for stat in stats], ['RAM', 'Download'])
        self.assertEqual(len(json.loads(cockpit.stats_payload({}, {}, ['disk']))['stats']), 1)

    def test_the_panel_block_is_validated(self):
        config = json.loads((Path(__file__).resolve().parents[1] / 'host/profiles.default.json').read_text(encoding='utf-8'))
        good = {'agents': ['claude'], 'apps': ['spotify.exe'], 'mic': False, 'stats': ['ram', 'net_down']}
        deck.validate_config(dict(config, panel=good))
        for bad in ({'agents': ['nobody']}, {'apps': ['a.exe'] * 4}, {'apps': ['not a program!']}, {'mic': 'yes'},
                    {'stats': ['cpu_heat']}, {'colour': 'red'}, 'all'):
            with self.assertRaises(ValueError, msg=bad):
                deck.validate_config(dict(config, panel=bad))



class RailTests(HostCase):
    def test_the_rail_has_the_chosen_screens_keys_always_and_only_shortcuts_that_exist(self):
        profiles = {'main': {'pages': {'main': [], 'tools': []}}, 'Chrome': {'pages': {'main': []}}}
        items = cockpit.rail_items({'screens': ['status', 'agents'],
                                    'shortcuts': [{'profile': 'Chrome', 'page': 'main', 'icon': 'lc:e0e8'},
                                                  {'profile': 'gone', 'page': 'main'}, {'profile': 'main', 'page': 'nope'}]}, profiles)
        self.assertEqual([item['k'] for item in items], ['keys', 'status', 'agents', 'page'])
        self.assertEqual((items[3]['p'], items[3]['g'], items[3]['i']), ('Chrome', 'main', 'lc:e0e8'))
        self.assertEqual([item['k'] for item in cockpit.rail_items({}, profiles)], ['keys', 'agents', 'mixer', 'status'])
        self.assertLessEqual(len(cockpit.rail_payload(items)), cockpit.MAX_LINE)

    def test_the_panel_block_checks_screens_and_shortcuts(self):
        config = json.loads((Path(__file__).resolve().parents[1] / 'host/profiles.default.json').read_text(encoding='utf-8'))
        deck.validate_config(dict(config, panel={'screens': ['keys', 'mixer'], 'shortcuts': [{'profile': 'main', 'page': 'main', 'icon': 'lc:e0e8'}]}))
        for bad in ({'screens': ['keys', 'keys']}, {'screens': ['weather']}, {'shortcuts': [{'profile': 'a', 'page': 'b'}] * 4},
                    {'shortcuts': [{'profile': 'a'}]}, {'shortcuts': [{'profile': 'a', 'page': 'b', 'icon': 'globe'}]}, {'shortcuts': 'x'}):
            with self.assertRaises(ValueError, msg=bad):
                deck.validate_config(dict(config, panel=bad))

    def test_a_shortcut_can_run_steps_and_an_older_panel_does_not_get_it(self):
        daemon = self.daemon()
        daemon.device_info = {'protocol': 4, 'firmwareVersion': '0.6.3'}
        steps = [{'type': 'hotkey', 'keys': 'ctrl+c'}]
        daemon.config['panel'] = {'shortcuts': [{'type': 'actions', 'actions': steps, 'label': 'Copy', 'icon': 'lc:e09e'}]}
        deck.validate_config(daemon.config)
        daemon.cockpit_tick(100.0)
        index = next(i for i, item in enumerate(daemon.rail_items) if item['k'] == 'act')
        sent = [call.args[0] for call in daemon.panel.send_line.call_args_list if call.args[0].startswith('AD_RAIL')][-1]
        self.assertIn('"k":"act"', sent.replace(' ', ''))
        self.assertNotIn('ctrl+c', sent, 'the steps stay on the PC')
        with unittest.mock.patch.object(daemon, 'start_actions') as run:
            daemon.handle_job(('rail', index))
        run.assert_called_once_with(steps)
        daemon.device_info = {'protocol': 4, 'firmwareVersion': '0.6.2'}
        daemon.cockpit_at = 0.0
        daemon.cockpit_tick(200.0)
        self.assertNotIn('act', [item['k'] for item in daemon.rail_items], 'firmware before 0.6.3 would refuse the whole rail')
        for bad in ({'type': 'actions', 'actions': []}, {'type': 'actions', 'actions': steps, 'label': 'x' * 41}, {'type': 'other', 'profile': 'a', 'page': 'b'}):
            with self.assertRaises(ValueError, msg=bad):
                deck.validate_config(dict(daemon.config, panel={'shortcuts': [bad]}))

    def test_the_status_screen_gets_as_many_readings_as_the_panel_shows(self):
        daemon = self.daemon()
        for info, count in (({'protocol': 4, 'firmwareVersion': '1.3.0', 'statsMax': 12}, 12),
                            ({'protocol': 4, 'firmwareVersion': '1.2.12'}, 8)):
            daemon.device_info, daemon.cockpit_at = info, 0.0
            daemon.cockpit_tick(100.0)
            sent = [call.args[0] for call in daemon.panel.send_line.call_args_list if call.args[0].startswith('AD_STATS ')][-1]
            self.assertEqual(len(json.loads(sent[len('AD_STATS '):])['stats']), count, info)

    def test_the_editor_learns_how_many_readings_the_panel_shows(self):
        daemon = host_support.test_daemon()
        daemon.log, daemon.panel = Mock(), Mock()
        with tempfile.TemporaryDirectory() as folder:
            daemon.runtime_path = Path(folder) / 'runtime.json'
            for info, count in (({'protocol': 4, 'statsMax': 12}, 12), ({'protocol': 4}, 8)):
                daemon.device_info = info
                daemon.publish_runtime(True, force=True)
                self.assertEqual(json.loads(daemon.runtime_path.read_text(encoding='utf-8'))['stats_max'], count)

    def test_a_shortcut_on_the_panel_goes_to_that_page_and_nonsense_does_nothing(self):
        daemon = self.daemon()
        daemon.device_info = {'protocol': 4}
        daemon.config['panel'] = {'shortcuts': [{'profile': 'main', 'page': 'system', 'icon': 'lc:e0ff'}]}
        daemon.cockpit_tick(100.0)
        start = (daemon.profile, daemon.page)
        index = next(i for i, item in enumerate(daemon.rail_items) if item['k'] == 'page')
        daemon.handle_job(('rail', index))
        self.assertEqual((daemon.profile, daemon.page), ('main', 'system'))
        for nothing in (99, -1):
            daemon.handle_job(('rail', nothing))
        self.assertEqual(daemon.page, 'system')
        keys = next(i for i, item in enumerate(daemon.rail_items) if item['k'] == 'keys')
        daemon.handle_job(('rail', keys))  # Keys tapped while the keys show: back to the page before the shortcut
        self.assertEqual((daemon.profile, daemon.page), start)
        daemon.switch_page('system')
        daemon.handle_job(('rail', keys))  # without a shortcut before it, Keys keeps the page you are on
        self.assertEqual(daemon.page, 'system')
        daemon.handle_job(('rail', index))
        daemon.switch_page('main')  # moved on by hand: the shortcut is forgotten
        daemon.handle_job(('rail', keys))
        self.assertEqual(daemon.page, 'main')
        daemon.dimmed = True
        with unittest.mock.patch.object(daemon, 'wake_display') as wake:
            daemon.handle_job(('rail', index))
        wake.assert_called_once()
        self.assertEqual(daemon.page, 'main', 'a tap on a dimmed panel only wakes it')

    def test_a_shortcut_into_another_profile_sends_only_its_page(self):
        daemon = self.daemon()
        daemon.device_info = {'protocol': 4}
        daemon.config['panel'] = {'shortcuts': [{'profile': 'coding', 'page': 'git', 'icon': 'lc:e0ff'}]}
        daemon.cockpit_tick(100.0)
        shortcut = next(i for i, item in enumerate(daemon.rail_items) if item['k'] == 'page')
        keys = next(i for i, item in enumerate(daemon.rail_items) if item['k'] == 'keys')
        for tap, shown in ((shortcut, ('coding', 'git')), (keys, ('main', 'main'))):
            daemon.panel.reset_mock()
            daemon.handle_job(('rail', tap))
            contexts = [json.loads(call.args[0].split(' ', 1)[1]) for call in daemon.panel.send_line.call_args_list
                        if call.args[0].startswith('AD_CONTEXT ')]
            self.assertEqual([(c['profile'], c['page']) for c in contexts], [shown], "the profile's first page is not sent first")
            daemon.panel.push_buttons.assert_called_once()



class CockpitDaemonTests(HostCase):
    def cockpit_daemon(self):
        daemon = self.daemon()
        daemon.device_info = {'protocol': 4}
        return daemon

    def test_an_older_panel_gets_no_cockpit_lines(self):
        daemon = self.daemon()
        daemon.device_info = {'protocol': 3}
        daemon.cockpit_tick(100.0)
        daemon.panel.send_line.assert_not_called()

    def test_only_changed_screens_are_sent_again(self):
        daemon = self.cockpit_daemon()
        faders = [{'id': 'speaker', 'name': 'Master', 'level': 50, 'muted': False, 'color': '#58E09B'}]
        with patch.object(cockpit, 'read_mixer', return_value=faders):
            daemon.cockpit_tick(100.0)
            sent = [call.args[0].split(' ', 1)[0] for call in daemon.panel.send_line.call_args_list]
            self.assertEqual(sorted(sent), ['AD_AGENTS', 'AD_MIXER', 'AD_RAIL', 'AD_STATS'])
            daemon.panel.send_line.reset_mock()
            daemon.cockpit_tick(100.5)  # less than a second later: nothing is read
            daemon.cockpit_tick(102.0)  # nothing changed: nothing is sent
            daemon.panel.send_line.assert_not_called()
            daemon.custom_vars['claude'] = 'waiting'
            daemon.cockpit_tick(104.0)
            self.assertEqual([call.args[0].split(' ', 1)[0] for call in daemon.panel.send_line.call_args_list], ['AD_AGENTS'])

    def test_a_question_that_opens_during_the_tick_is_not_overwritten_by_an_older_line(self):
        daemon = self.cockpit_daemon()
        question = {'agent': 'claude', 'text': 'Run tests?'}
        daemon.permissions.current = Mock(return_value=None)

        def mixer(*_):  # the worker opens a question while the main loop reads the mixer
            daemon.permissions.current.return_value = question
            return []
        with patch.object(cockpit, 'read_mixer', side_effect=mixer):
            daemon.cockpit_tick(100.0)
        agents = [call.args[0] for call in daemon.panel.send_line.call_args_list if call.args[0].startswith('AD_AGENTS')]
        expected = cockpit.agents_payload(daemon.agent_view(), daemon.agents, question, None)
        self.assertEqual(agents, [f'AD_AGENTS {expected}'])
        self.assertEqual(daemon.cockpit_sent['AD_AGENTS'], expected)

    @unittest.skipIf(sys.platform != 'win32', 'pycaw is Windows only')
    def test_without_a_microphone_the_mixer_still_shows_the_speaker(self):
        from unittest.mock import Mock
        speaker = Mock(**{'GetMasterVolumeLevelScalar.return_value': 0.5, 'GetMute.return_value': False})
        from platform_windows import audio as win_audio
        with patch('platform_windows.audio._with_audio', side_effect=lambda work: work({'speaker': speaker, 'mic': None})), \
                patch('platform_windows.audio._all_sessions', return_value=[]):
            self.assertEqual([fader['id'] for fader in win_audio.read_mixer()], ['speaker'])

    def test_a_missing_sound_device_does_not_stop_the_other_screens(self):
        daemon = self.cockpit_daemon()
        with patch.object(cockpit, 'read_mixer', side_effect=OSError('no audio device')):
            daemon.cockpit_tick(100.0)
        sent = [call.args[0].split(' ', 1)[0] for call in daemon.panel.send_line.call_args_list]
        self.assertEqual(sorted(sent), ['AD_AGENTS', 'AD_RAIL', 'AD_STATS'])

    def test_a_fader_and_a_mute_touch_reach_the_sound_of_that_program(self):
        daemon = self.cockpit_daemon()
        with patch.object(deck, 'control_audio') as audio:
            daemon.handle_job(('fader', 'app:Spotify.exe', 40))
            daemon.handle_job(('mute', 'mic'))
        self.assertEqual([call.args for call in audio.call_args_list], [('app:Spotify.exe', 'volume', 40), ('mic', 'toggle')])

    def test_a_touch_on_a_remote_fader_reaches_that_device_and_never_the_pcs_sound(self):
        daemon = self.cockpit_daemon()
        import remote_devices
        with patch.object(deck, 'control_audio') as audio, patch.object(remote_devices, 'set_volume') as volume, \
                patch.object(remote_devices, 'toggle_mute') as mute:
            daemon.handle_job(('fader', 'remote:0123456789', 35))
            daemon.handle_job(('mute', 'remote:0123456789'))
            daemon.handle_job(('fader', 'speaker', 10))
        volume.assert_called_once_with('remote:0123456789', 35)
        mute.assert_called_once_with('remote:0123456789')
        self.assertEqual([call.args for call in audio.call_args_list], [('speaker', 'volume', 10)])

    def test_a_remote_media_key_runs_the_action_with_its_device(self):
        daemon = self.cockpit_daemon()
        import remote_devices
        with patch.object(remote_devices, 'control_media') as media:
            daemon.run_action({'type': 'remote_media', 'op': 'next', 'device': 'ce7eff39_phone'})
            daemon.run_action({'type': 'remote_media', 'op': 'playpause'})
            daemon.run_action({'type': 'remote_media', 'op': 'volumeup', 'step': 10})
        self.assertEqual([call.args for call in media.call_args_list],
                         [('next', 'ce7eff39_phone', 5), ('playpause', 'first', 5), ('volumeup', 'first', 10)])

    def test_an_agent_button_brings_the_tool_to_the_front_and_is_published_as_an_event(self):
        daemon = self.cockpit_daemon()
        import daemon_ticks
        with patch.object(daemon_ticks, 'focus_existing_process', return_value=True) as focus:
            daemon.handle_job(('agent', 'claude', 'allow'))
        focus.assert_called_once_with('claude.exe')
        event = daemon.events.since(0, None)[-1]
        self.assertEqual((event['type'], event['agent'], event['action']), ('agent', 'claude', 'allow'))

    def test_touch_lines_from_the_panel_become_jobs_and_nonsense_is_ignored(self):
        daemon = self.cockpit_daemon()
        lines = ['{"type":"fader","id":"speaker","level":250}', '{"type":"mute","id":"mic"}',
                 '{"type":"agent","id":"claude","do":"allow"}', '{"type":"agent","id":"nobody","do":"allow"}',
                 '{"type":"agent","id":"claude","do":"format-disk"}', '{"type":"fader","id":"speaker","level":"loud"}']
        daemon.panel.read_lines.side_effect = [lines, OSError('unplugged')]
        daemon.reader_loop(daemon.panel)
        jobs = []
        while not daemon.jobs.empty():
            jobs.append(daemon.jobs.get_nowait())
        self.assertEqual(jobs, [('fader', 'speaker', 100), ('mute', 'mic'), ('agent', 'claude', 'allow')])


if __name__ == '__main__':
    unittest.main()
