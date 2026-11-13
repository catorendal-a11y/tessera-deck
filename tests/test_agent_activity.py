"""The agents screen without hooks: working and idle come from the tools' own session files."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import agent_activity
import cockpit


def json_lanes(variables):
    return __import__('json').loads(cockpit.agents_payload(variables, {}))['agents']


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.now = 1_700_000_000.0

    def session(self, name, text, age):
        folder = self.root / 'claude' / name
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 's.jsonl'
        path.write_text(text, encoding='utf-8')
        os.utime(path, (self.now - age, self.now - age))

    def activity(self):
        return agent_activity.AgentActivity(self.root / 'claude', self.root / 'codex', clock=lambda: self.now)

    def test_a_file_written_a_moment_ago_is_a_tool_at_work_in_its_project(self):
        self.session('p', '{"cwd":"C:\\Users\\me\\Documents\\tessera"}\n{"type":"tool_use","id":"t1","name":"Bash"}\n', 3)
        seen = self.activity().read()['claude']
        self.assertEqual((seen['state'], seen['project'], seen['tool']), ('working', 'tessera', 'Bash'))

    def test_an_older_file_is_idle_and_a_missing_folder_is_no_tool(self):
        self.session('p', '{"cwd":"C:\\x\\app"}\n', 300)
        activity = self.activity().read()
        self.assertEqual(activity['claude']['state'], 'idle')
        self.assertNotIn('codex', activity)

    def test_the_screen_shows_working_idle_and_lets_a_hook_win(self):
        merged = agent_activity.merge({}, {'claude': {'state': 'working', 'project': 'tessera', 'age': 2, 'tool': 'Edit'}}, {}, lambda: self.now)
        lane = __import__('json').loads(cockpit.agents_payload(merged, {}))['agents'][0]
        self.assertEqual((lane['state'], lane['text'], lane['sub']), ('working', 'Using Edit', 'tessera'))
        idle = agent_activity.merge({}, {'codex': {'state': 'idle', 'project': 'x', 'age': 120, 'tool': ''}}, {}, lambda: self.now)
        self.assertEqual(idle['codex'], 'idle')
        self.assertTrue(idle['codex.message'].startswith('Last active'))
        waiting = agent_activity.merge({'claude': 'waiting', 'claude.message': 'Allow?'},
                                       {'claude': {'state': 'working', 'project': 'p', 'age': 1, 'tool': ''}}, {}, lambda: self.now)
        self.assertEqual(waiting['claude'], 'waiting')

    def test_a_hook_state_of_a_killed_tool_is_dropped_but_a_real_wait_stays(self):
        stale = {'claude': {'state': 'idle', 'project': 'p', 'age': 99999, 'tool': ''}}
        hook = {'claude': 'waiting', 'claude.message': 'Allow?'}
        gone = agent_activity.merge(hook, stale, {'claude': False}, lambda: self.now)
        self.assertNotIn('claude', gone)
        self.assertEqual(json_lanes(gone), [], 'no lane for a tool that is gone')
        self.assertEqual(agent_activity.merge(hook, stale, {}, lambda: self.now)['claude'], 'waiting', 'not scanned yet')
        recent = {'claude': {'state': 'idle', 'project': 'p', 'age': 600, 'tool': ''}}
        self.assertEqual(agent_activity.merge(hook, recent, {'claude': False}, lambda: self.now)['claude'], 'waiting')

    def test_only_the_asked_lane_is_marked_as_a_question(self):
        asking = {'agent': 'claude', 'text': 'Allow Bash?'}
        lanes = __import__('json').loads(cockpit.agents_payload({'claude': 'waiting', 'codex': 'waiting'}, {}, asking))['agents']
        self.assertEqual({lane['id']: lane.get('q') for lane in lanes}, {'claude': 1, 'codex': None})

    def test_an_old_idle_tool_is_left_out_unless_its_program_runs(self):
        stale = {'claude': {'state': 'idle', 'project': '', 'age': 99999, 'tool': ''}}
        self.assertNotIn('claude', agent_activity.merge({}, stale, {}, lambda: self.now))
        self.assertEqual(agent_activity.merge({}, stale, {'claude': True}, lambda: self.now)['claude'], 'idle')


if __name__ == '__main__':
    unittest.main()
