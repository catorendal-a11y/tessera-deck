"""Counters and timers: operations, persistence across restarts, and their use in labels, gauges and bindings."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck
from live_state import LiveState, clock_text


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class StateCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.local.json'
        self.clock = Clock()
        self.state = LiveState(self.path, self.clock)

    def restart(self):
        self.state.flush()
        self.state = LiveState(self.path, self.clock)
        return self.state


class CounterTests(StateCase):
    def count(self, **action):
        return self.state.apply_counter(dict({'name': 'laps'}, **action))

    def test_increment_decrement_set_and_reset(self):
        self.assertEqual([self.count(), self.count(), self.count(step=5)], [1, 2, 7])
        self.assertEqual(self.count(op='dec', step=3), 4)
        self.assertEqual(self.count(op='set', value=40), 40)
        self.assertEqual(self.count(op='reset'), 0)
        self.assertEqual(self.count(op='reset', value=10), 10)

    def test_limits_clamp_and_wrap(self):
        self.assertEqual([self.count(max=2) for _ in range(4)], [1, 2, 2, 2])
        self.assertEqual(self.count(op='dec', step=9, min=0), 0)
        self.state.apply_counter({'name': 'dial', 'op': 'set', 'value': 9})
        self.assertEqual(self.state.apply_counter({'name': 'dial', 'min': 0, 'max': 9, 'wrap': True}), 0)
        self.assertEqual(self.state.apply_counter({'name': 'dial', 'op': 'dec', 'min': 0, 'max': 9, 'wrap': True}), 9)

    def test_bad_counter_actions_are_rejected(self):
        for bad in ({'name': ''}, {'name': 'a b'}, {'name': 'x', 'op': 'explode'}, {'name': 'x', 'step': 0},
                    {'name': 'x', 'step': 1.5}, {'name': 'x', 'min': 5, 'max': 1}, {'name': 'x', 'wrap': 'yes'},
                    {'name': 'x', 'value': 10 ** 12}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.state.apply_counter(bad)

    def test_counters_survive_a_restart(self):
        self.count(step=3)
        self.assertEqual(self.restart().counters, {'laps': 3})
        self.assertEqual(self.restart().variables()['counter:laps'], '3')

    def test_the_number_of_counters_is_bounded(self):
        for index in range(200):
            self.state.apply_counter({'name': f'c{index}'})
        with self.assertRaises(ValueError):
            self.state.apply_counter({'name': 'one-too-many'})
        self.assertEqual(self.state.apply_counter({'name': 'c0'}), 2)


class TimerTests(StateCase):
    def timer(self, **action):
        return self.state.apply_timer(dict({'name': 'pasta'}, **action))

    def test_start_counts_down_and_finishes_once(self):
        self.assertEqual(self.timer(op='start', seconds=90), 'running')
        self.assertEqual(self.state.variables()['timer:pasta'], '01:30')
        self.clock.now += 30.4
        self.assertEqual(self.state.variables()['timer:pasta'], '01:00')
        self.assertEqual(self.state.tick(), [])
        self.clock.now += 60
        done = self.state.tick()
        self.assertEqual([item['name'] for item in done], ['pasta'])
        self.assertEqual(done[0]['message'], 'Timer pasta finished')
        self.assertEqual(self.state.tick(), [], 'a timer is announced only once')
        self.assertEqual(self.state.variables()['timer:pasta'], 'DONE')
        self.assertEqual(self.state.variables()['timer-state:pasta'], 'DONE')

    def test_pause_resume_stop_and_toggle(self):
        self.timer(op='start', seconds=100)
        self.clock.now += 40
        self.assertEqual(self.timer(op='pause'), 'paused')
        self.clock.now += 500
        self.assertEqual(self.state.variables()['timer:pasta'], '01:00', 'a paused timer does not run')
        self.assertEqual(self.timer(op='resume'), 'running')
        self.clock.now += 61
        self.assertEqual(len(self.state.tick()), 1)
        self.assertEqual(self.timer(op='stop'), 'idle')
        self.assertEqual(self.state.variables()['timer:pasta'], '01:40', 'an idle timer shows its length')
        self.assertEqual([self.timer(), self.timer(), self.timer()], ['running', 'paused', 'running'])

    def test_notification_text_sound_and_actions_come_with_the_finished_timer(self):
        actions = [{'type': 'press', 'id': 3}]
        self.timer(op='start', seconds=5, notify='Dinner is ready', sound=True, actions=actions)
        self.clock.now += 5
        self.assertEqual(self.state.tick(), [{'name': 'pasta', 'message': 'Dinner is ready', 'sound': True,
                                              'actions': actions}])

    def test_a_running_timer_keeps_counting_while_closed_and_a_late_one_is_done(self):
        self.timer(op='start', seconds=600)
        self.clock.now += 200
        restarted = self.restart()
        self.assertEqual(restarted.variables()['timer:pasta'], '06:40')
        self.clock.now += 1000
        late = self.restart()
        self.assertEqual(late.variables()['timer-state:pasta'], 'DONE')
        self.assertEqual(late.tick(), [], 'nothing is announced for a timer that ended while Tessera was closed')

    def test_a_paused_timer_survives_a_restart(self):
        self.timer(op='start', seconds=100)
        self.clock.now += 25
        self.timer(op='pause')
        self.clock.now += 9999
        self.assertEqual(self.restart().variables()['timer:pasta'], '01:15')

    def test_bad_timer_actions_are_rejected(self):
        for bad in ({'name': 'x', 'op': 'start'}, {'name': 'x', 'op': 'pause'}, {'name': 'x', 'seconds': 0},
                    {'name': 'x', 'seconds': 10 ** 9}, {'name': 'x', 'notify': 'n' * 500}, {'name': 'x', 'sound': 1},
                    {'name': 'x', 'actions': 'press'}, {'name': 'a:b', 'op': 'start', 'seconds': 5}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.state.apply_timer(bad)

    def test_raw_values_feed_gauges_in_seconds(self):
        self.timer(op='start', seconds=120)
        self.clock.now += 30
        self.state.apply_counter({'name': 'laps', 'step': 4})
        self.assertEqual(self.state.raw(), {'counter:laps': 4.0, 'timer:pasta': 90.0})

    def test_clock_text(self):
        self.assertEqual([clock_text(value) for value in (0, 0.2, 59.9, 60, 3599, 3600, 3725)],
                         ['00:00', '00:01', '01:00', '01:00', '59:59', '1:00:00', '1:02:05'])


class PersistenceTests(StateCase):
    def test_damaged_and_hostile_files_start_clean(self):
        for content in ('', 'not json', '[]', '{"version": 99}', '{"version":1,"counters":5,"timers":"x"}',
                        '{"version":1,"counters":{"a b":1,"ok":"x","big":99999999999},'
                        '"timers":{"t":{"state":"weird","duration":5},"u":{"state":"idle","duration":-4},"v":7}}'):
            self.path.write_text(content)
            state = LiveState(self.path, self.clock)
            self.assertEqual((state.counters, state.timers), ({}, {}), msg=content)

    def test_only_changes_are_written(self):
        self.state.flush()
        self.assertFalse(self.path.exists())
        self.state.apply_counter({'name': 'a'})
        self.state.flush()
        written = self.path.stat().st_mtime_ns
        self.state.flush()
        self.assertEqual(self.path.stat().st_mtime_ns, written)
        self.assertEqual(json.loads(self.path.read_text())['counters'], {'a': 1})


class DaemonTests(StateCase):
    def daemon(self):
        daemon = deck.Daemon(types.SimpleNamespace(profiles=str(ROOT / 'host/profiles.default.json'), port='TEST',
                                                   verbose=False, no_focus=True, deck_only=True))
        daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
        daemon.live = self.state
        return daemon

    def test_actions_update_the_labels_gauges_and_bindings(self):
        daemon = self.daemon()
        daemon.profile, daemon.page = 'main', 'main'
        button = next(b for b in daemon.config['profiles']['main']['pages']['main'] if b['id'] == 1)
        button.update(label='$(counter:laps) / $(timer:pasta)',
                      gauge={'key': 'timer:pasta', 'max': 100, 'fmt': 'clock'})
        daemon.run_action({'type': 'counter', 'name': 'laps', 'step': 2})
        daemon.run_action({'type': 'timer', 'name': 'pasta', 'op': 'start', 'seconds': 100})
        self.clock.now += 25
        entry = next(item for item in daemon.current_buttons() if item['id'] == 1)
        self.assertEqual(entry['label'], '2 / 01:15')
        self.assertEqual(entry['gauge'], {'p': 75, 't': '01:15'})

    def test_a_toggle_key_can_follow_a_running_timer(self):
        daemon = self.daemon()
        daemon.profile, daemon.page = 'main', 'main'
        button = next(b for b in daemon.config['profiles']['main']['pages']['main'] if b['id'] == 2)
        button.update(states=[{'label': 'Start', 'actions': []}, {'label': 'Pause', 'actions': []}],
                      bind='timer-running:pomodoro')
        deck.validate_config(daemon.config)

        def shown():
            return next(item for item in daemon.current_buttons() if item['id'] == 2)['label']

        self.assertEqual(shown(), 'Start')
        daemon.run_action({'type': 'timer', 'name': 'pomodoro', 'op': 'start', 'seconds': 1500})
        self.assertEqual(shown(), 'Pause')
        button['bind'] = 'timer-running:bad name'
        with self.assertRaises(ValueError):
            deck.validate_config(daemon.config)

    def test_a_finished_timer_raises_a_notice_and_runs_its_actions(self):
        daemon = self.daemon()
        daemon.run_action({'type': 'timer', 'name': 'tea', 'op': 'start', 'seconds': 5, 'notify': 'Tea!',
                           'actions': [{'type': 'set', 'variable': 'tea', 'value': 'ready'}]})
        self.clock.now += 6
        daemon.live_tick()
        self.assertEqual(daemon.notices[-1]['message'], 'Tea!')
        self.assertEqual(daemon.jobs.get_nowait()[0], 'actions')
        self.assertEqual(daemon.jobs.get_nowait(), ('push',))
        self.assertTrue(self.path.exists())

    def test_the_validator_accepts_and_rejects_the_new_actions(self):
        config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        button = config['profiles']['main']['pages']['main'][0]
        button['actions'] = [{'type': 'counter', 'name': 'laps', 'op': 'inc'},
                             {'type': 'timer', 'name': 'tea', 'op': 'toggle', 'seconds': 60,
                              'actions': [{'type': 'press', 'id': 2}]}]
        deck.validate_config(config)
        for bad in ({'type': 'counter', 'name': 'x', 'op': 'bogus'}, {'type': 'timer', 'name': 'x', 'seconds': -1},
                    {'type': 'timer', 'name': 'x', 'actions': [{'type': 'hotkey', 'keys': 'not-a-key'}]}):
            button['actions'] = [bad]
            with self.assertRaises(ValueError, msg=repr(bad)):
                deck.validate_config(config)


if __name__ == '__main__':
    unittest.main()
