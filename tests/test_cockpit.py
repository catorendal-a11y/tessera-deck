"""The cockpit screens of a protocol 4 panel: what the host sends and what a touch on them does."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import cockpit
import tesserad as deck
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
        self.assertEqual((by_name['Disk']['p'], by_name['CPU load']['p'], by_name['CPU load']['warn']), (93, 4, False))
        self.assertEqual((by_name['GPU temp']['value'], by_name['GPU temp']['p']), ('--', 0))
        self.assertEqual(len(stats), 8)

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
        for bad in ({'agents': ['nobody']}, {'apps': ['a.exe'] * 4}, {'apps': ['notaprogram']}, {'mic': 'yes'},
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

    def test_a_shortcut_on_the_panel_goes_to_that_page_and_nonsense_does_nothing(self):
        daemon = self.daemon()
        daemon.device_info = {'protocol': 4}
        daemon.config['panel'] = {'shortcuts': [{'profile': 'main', 'page': 'system', 'icon': 'lc:e0ff'}]}
        daemon.cockpit_tick(100.0)
        index = next(i for i, item in enumerate(daemon.rail_items) if item['k'] == 'page')
        daemon.handle_job(('rail', index))
        self.assertEqual((daemon.profile, daemon.page), ('main', 'system'))
        daemon.page = 'main'
        for nothing in (0, 99, -1):
            daemon.handle_job(('rail', nothing))
        self.assertEqual(daemon.page, 'main')



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

    @unittest.skipIf(sys.platform != 'win32', 'pycaw is Windows only')
    def test_without_a_microphone_the_mixer_still_shows_the_speaker(self):
        from unittest.mock import Mock
        speaker = Mock(**{'GetMasterVolumeLevelScalar.return_value': 0.5, 'GetMute.return_value': False})
        with patch('pc_state._with_audio', side_effect=lambda work: work({'speaker': speaker, 'mic': None})), \
                patch('pycaw.pycaw.AudioUtilities.GetAllSessions', return_value=[]):
            self.assertEqual([fader['id'] for fader in cockpit.read_mixer()], ['speaker'])

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
