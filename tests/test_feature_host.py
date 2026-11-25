"""Host side of the small editor features: profile page, weekday triggers, kept backups, more readings, state packs."""
import json
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import action_preview
import cockpit
import config_store
import tessera_app
import tesserad as deck
from host_support import HostCase, test_daemon


def two_profiles():
    key = {'id': 1, 'label': 'A', 'icon': 'ok', 'actions': []}
    return {'default_profile': 'One', 'profiles': {'One': {'match': [], 'pages': {'first': [key], 'second': [key]}},
                                                   'Two': {'match': [], 'pages': {'home': [key], 'extra': [key]}}}}


def with_actions(config, actions, where='triggers'):
    config = json.loads(json.dumps(config))
    if where == 'triggers':
        config['triggers'] = actions
    return config


class ProfilePageTests(HostCase):
    def check(self, action):
        deck.validate_config(with_actions(two_profiles(), [{'when': {'type': 'startup'}, 'actions': [action]}]))

    def test_a_profile_step_may_name_a_page_of_that_profile(self):
        self.check({'type': 'profile', 'profile': 'Two', 'page': 'extra'})

    def test_a_page_the_profile_does_not_have_is_refused_with_both_names(self):
        for page in ('second', 'nope', '', 5):
            with self.assertRaises(ValueError, msg=page) as raised:
                self.check({'type': 'profile', 'profile': 'Two', 'page': page})
        with self.assertRaises(ValueError) as raised:
            self.check({'type': 'profile', 'profile': 'Two', 'page': 'second'})
        self.assertIn('second', str(raised.exception))
        self.assertIn('Two', str(raised.exception))

    def test_running_the_step_goes_straight_to_the_page(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profiles.json'
            path.write_text(json.dumps(two_profiles()), encoding='utf-8')
            daemon = test_daemon(path)
            daemon.panel, daemon.log = Mock(), Mock()
            daemon.profile, daemon.page = 'One', 'first'
            daemon.run_action({'type': 'profile', 'profile': 'Two', 'page': 'extra'})
            self.assertEqual((daemon.profile, daemon.page), ('Two', 'extra'))
            daemon.run_action({'type': 'profile', 'profile': 'One'})
            self.assertEqual((daemon.profile, daemon.page), ('One', 'first'))
            daemon.run_action({'type': 'profile', 'profile': 'One', 'page': 'second'})  # already in that profile
            self.assertEqual((daemon.profile, daemon.page), ('One', 'second'))

    def test_the_dry_run_names_the_page(self):
        report = action_preview.preview([{'type': 'profile', 'profile': 'Two', 'page': 'extra'}], {})
        self.assertEqual(report['steps'][0]['text'], 'Switch to profile "Two", page "extra"')
        self.assertEqual(action_preview.preview([{'type': 'profile', 'profile': 'Two'}], {})['steps'][0]['text'], 'Switch to profile "Two"')


class DailyDaysTests(HostCase):
    def run_days(self, days, schedule):
        """schedule: (day, time) pairs, each a new tick; returns the days on which the trigger fired."""
        fired = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profiles.json'
            config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
            when = {'type': 'daily', 'at': '09:00'}
            if days is not None:
                when['days'] = days
            config['triggers'] = [{'when': when, 'actions': [{'type': 'back'}]}]
            path.write_text(json.dumps(config), encoding='utf-8')
            clock, day = ['08:00'], ['2026-11-16']  # a Monday
            fake_time = types.SimpleNamespace(time=time.time, strftime=lambda pattern: day[0] if pattern == '%Y-%m-%d' else clock[0])
            with patch('daemon_ticks.time', fake_time):
                daemon = test_daemon(path)
                daemon.log = Mock()
                for number, (when_day, when_time) in enumerate(schedule, 1):
                    day[0], clock[0] = when_day, when_time
                    daemon.trigger_tick(number)
                    while not daemon.jobs.empty():
                        daemon.jobs.get_nowait()
                        fired.append(when_day)
                self.runs = dict(daemon.daily_runs())
        return fired

    def test_only_the_listed_days_run_and_an_unlisted_day_is_not_recorded(self):
        schedule = [('2026-11-16', '08:00'), ('2026-11-16', '09:00'), ('2026-11-17', '09:00'), ('2026-11-17', '12:00'),
                    ('2026-11-18', '09:00')]
        self.assertEqual(self.run_days(['mon', 'wed'], schedule), ['2026-11-16', '2026-11-18'])
        self.assertEqual(self.runs, {'0:09:00': '2026-11-18'})
        self.assertEqual(self.run_days(['tue'], schedule), ['2026-11-17'], 'a listed day still runs once a day')

    def test_without_days_it_runs_every_day_as_before(self):
        schedule = [('2026-11-16', '08:00'), ('2026-11-16', '09:00'), ('2026-11-16', '10:00'), ('2026-11-17', '09:00')]
        self.assertEqual(self.run_days(None, schedule), ['2026-11-16', '2026-11-17'])

    def test_a_listed_day_after_an_unlisted_one_runs_when_the_host_was_off_at_the_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profiles.json'
            config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
            config['triggers'] = [{'when': {'type': 'daily', 'at': '09:00', 'days': ['mon', 'tue']}, 'actions': [{'type': 'back'}]}]
            path.write_text(json.dumps(config), encoding='utf-8')
            day = ['2026-11-16']
            fake_time = types.SimpleNamespace(time=time.time, strftime=lambda pattern: day[0] if pattern == '%Y-%m-%d' else '10:00')
            with patch('daemon_ticks.time', fake_time):
                first = test_daemon(path)
                first.log = Mock()
                first.trigger_tick(1)  # Monday: the host started after 09:00 and never ran it, so it waits
                self.assertTrue(first.jobs.empty())
                day[0] = '2026-11-17'
                first.trigger_tick(2)
                self.assertEqual(first.jobs.get_nowait()[0], 'actions')

    def test_days_must_be_a_list_of_weekday_names_without_repeats(self):
        base = two_profiles()
        for days in (['mon', 'wed', 'sun'], ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'], ['fri']):
            deck.validate_config(with_actions(base, [{'when': {'type': 'daily', 'at': '09:00', 'days': days}, 'actions': []}]))
        for days in ([], ['mon', 'mon'], ['monday'], ['Mon'], 'mon', None, [1], ['mon', None]):
            with self.assertRaises(ValueError, msg=days) as raised:
                deck.validate_config(with_actions(base, [{'when': {'type': 'daily', 'at': '09:00', 'days': days}, 'actions': []}]))
            self.assertIn('days', str(raised.exception))
        with self.assertRaises(ValueError):  # days belong to a daily trigger only
            deck.validate_config(with_actions(base, [{'when': {'type': 'startup', 'days': ['mon']}, 'actions': []}]))


class KeepBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'profiles.json'
        self.now = [1_800_000_000.0]

    def make(self, label, **options):
        config = {'default_profile': 'Main', 'profiles': {'Main': {'match': [], 'pages': {
            'First': [{'id': 1, 'label': label, 'icon': 'ok', 'actions': [{'type': 'hotkey', 'keys': 'ctrl+c'}]}]}}}}
        self.path.write_text(json.dumps(config), encoding='utf-8')
        self.now[0] += 1000
        return config_store.backup(self.path, now=lambda: self.now[0], **options)

    def test_a_kept_backup_is_listed_as_kept_and_the_others_are_not(self):
        first, second = self.make('a'), self.make('b')
        new = config_store.keep_backup(self.path, first.name, True)
        self.assertEqual(new, first.name[:-5] + '-keep.json')
        listing = {item['name']: item['kept'] for item in config_store.list_backups(self.path)}
        self.assertEqual(listing, {second.name: False, new: True})
        self.assertEqual(config_store.keep_backup(self.path, new, False), first.name, 'it can be let go again')
        self.assertFalse(any(item['kept'] for item in config_store.list_backups(self.path)))

    def test_pruning_never_removes_a_kept_backup_and_does_not_count_it(self):
        first = self.make('v0')
        kept = config_store.keep_backup(self.path, first.name, True)
        for number in range(1, 7):
            self.make(f'v{number}', keep=3)
        listing = config_store.list_backups(self.path)
        self.assertEqual(sorted(item['kept'] for item in listing), [False, False, False, True])
        self.assertIn(kept, [item['name'] for item in listing])

    def test_a_kept_backup_restores(self):
        first = self.make('original')
        kept = config_store.keep_backup(self.path, first.name, True)
        self.make('later')
        restored = config_store.read_backup(self.path, kept)
        self.assertEqual(restored['profiles']['Main']['pages']['First'][0]['label'], 'original')

    def test_only_a_listed_backup_can_be_kept(self):
        first = self.make('a')
        for name in ('../profiles.json', '../../etc/passwd', 'profiles.json', 'profiles-20200101-000000.json', '', None, 5,
                     first.name[:-5] + '-keep-keep.json'):
            with self.assertRaises(ValueError, msg=name):
                config_store.keep_backup(self.path, name, True)
        self.assertEqual(config_store.keep_backup(self.path, first.name, False), first.name, 'not kept: nothing to change')
        self.assertTrue((first.parent / first.name).exists())

    def test_the_editor_command_answers_with_the_new_name(self):
        first = self.make('a')
        editor = tessera_app.Editor(self.path, dashboard=lambda: {'running': False, 'device': {}})
        answer = editor.command('keep-backup', {'name': first.name, 'keep': True})
        self.assertEqual(answer, {'name': first.name[:-5] + '-keep.json'})
        self.assertTrue(editor.command('backups', {})['backups'][0]['kept'])
        self.assertEqual(editor.command('keep-backup', {'name': answer['name'], 'keep': False}), {'name': first.name})
        with self.assertRaises(ValueError):
            editor.command('keep-backup', {'name': '../x.json', 'keep': True})


class ReadingTests(unittest.TestCase):
    NEW = ('net_up', 'uptime', 'cpu_clock', 'cpu_power', 'gpu_power', 'gpu_clock', 'gpu_fan', 'fps')
    OLD = ('cpu_load', 'cpu_temp', 'ram', 'disk', 'gpu_load', 'gpu_temp', 'vram', 'net_down')

    def test_the_choices_are_the_old_eight_and_the_new_eight(self):
        self.assertEqual(set(cockpit.STAT_IDS), set(self.OLD + self.NEW))
        self.assertEqual(len(cockpit.STAT_IDS), 16)

    def test_without_a_choice_the_panel_gets_the_old_eight(self):
        display = {key: '1' for key in cockpit.STAT_IDS}
        names = [stat['name'] for stat in json.loads(cockpit.stats_payload(display, {}))['stats']]
        self.assertEqual(len(names), 8)
        self.assertEqual(names[-1], 'Download')
        self.assertNotIn('Upload', names)

    def test_every_reading_fits_the_panels_text_limits(self):
        display = {key: '123456789' for key in cockpit.STAT_IDS}
        for key in cockpit.STAT_IDS:
            stat = json.loads(cockpit.stats_payload(display, {}, [key]))['stats'][0]
            self.assertTrue(0 < len(stat['name']) <= 15, key)
            self.assertLessEqual(len(stat['unit']), 5, key)
            self.assertLessEqual(len(stat['value']), 7, key)

    def test_a_missing_reading_shows_dashes_and_a_known_one_fills_its_bar(self):
        stats = json.loads(cockpit.stats_payload({'net_up': '2.0M'}, {'net_up': 2 * 1024 * 1024, 'fps': None}, ['net_up', 'fps', 'uptime']))['stats']
        by_name = {stat['name']: stat for stat in stats}
        self.assertEqual(by_name['Upload']['value'], '2.0M')
        self.assertEqual(by_name['Upload']['p'], 20)
        self.assertEqual((by_name['FPS']['value'], by_name['FPS']['p']), ('--', 0))
        self.assertEqual(by_name['Uptime']['value'], '--')

    def test_without_a_choice_a_panel_with_room_for_twelve_gets_the_first_twelve(self):
        display = {key: '1' for key in cockpit.STAT_IDS}
        names = [stat['name'] for stat in json.loads(cockpit.stats_payload(display, {}, limit=12))['stats']]
        self.assertEqual(names, [label for label, *_ in cockpit.STATS][:12])

    def test_never_more_than_the_panel_shows_are_sent(self):
        display = {key: '1' for key in cockpit.STAT_IDS}
        for limit in (8, 12):
            stats = json.loads(cockpit.stats_payload(display, {}, list(cockpit.STAT_IDS), limit=limit))['stats']
            self.assertEqual(len(stats), limit)
        self.assertEqual(len(json.loads(cockpit.stats_payload(display, {}, list(cockpit.STAT_IDS)))['stats']), 8)

    def test_the_configuration_refuses_more_than_twelve_and_accepts_the_new_ones(self):
        def check(stats):
            config = two_profiles()
            config['panel'] = {'stats': stats}
            deck.validate_config(config)
        check(list(self.NEW))
        check(['fps', 'cpu_load'])
        check(list(cockpit.STAT_IDS[:12]))
        with self.assertRaises(ValueError) as raised:
            check(list(cockpit.STAT_IDS))
        self.assertIn('12', str(raised.exception))
        with self.assertRaises(ValueError):
            check(['fps', 'nonsense'])


class StatePackTests(unittest.TestCase):
    def packs(self):
        tessera_app.action_pack_catalog.cache_clear()
        return {pack['name']: pack for pack in tessera_app.action_pack_catalog()['packs']}

    def test_the_three_new_packs_are_there(self):
        packs = self.packs()
        mic, speaker, pomodoro = packs['Mic mute (shows state)'], packs['Speaker mute (shows state)'], packs['Pomodoro 25 min']
        self.assertEqual((mic['bind'], speaker['bind']), ('mic_muted', 'speaker_muted'))
        self.assertEqual([step['target'] for pack in (mic, speaker) for state in pack['states'] for step in state['actions']],
                         ['mic', 'mic', 'speaker', 'speaker'])
        self.assertEqual(pomodoro['label'], '$(timer:pomodoro)')
        step = pomodoro['actions'][0]
        self.assertEqual((step['type'], step['name'], step['op'], step['seconds']), ('timer', 'pomodoro', 'toggle', 1500))
        self.assertTrue(step['notify'])

    def test_a_bad_state_pack_is_refused(self):
        real = json.loads((ROOT / 'host/action_packs.json').read_text(encoding='utf-8'))
        real['packs'].append({'group': 'Media', 'name': 'Bad', 'icon': 'ok', 'actions': [], 'bind': 'mic_muted', 'states': [{'label': 'x', 'actions': []}]})
        tessera_app.action_pack_catalog.cache_clear()
        with patch('tessera_app.json.loads', return_value=real), self.assertRaises(ValueError):
            tessera_app.action_pack_catalog()
        tessera_app.action_pack_catalog.cache_clear()


if __name__ == '__main__':
    unittest.main()
