"""A notice when an agent starts waiting for you or finishes long work, and the tray says who waits."""
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
from host_support import HostCase


class NoticeTests(HostCase):
    def tick(self, daemon, now, **variables):
        daemon.custom_vars.clear()
        daemon.custom_vars.update(variables)
        daemon.activity.read = lambda: {}
        daemon.agent_notice_tick(now)
        return [(notice['title'], notice['message']) for notice in daemon.notices]

    def test_the_first_look_is_silent_and_a_new_wait_is_announced_once(self):
        daemon = self.daemon()
        self.assertEqual(self.tick(daemon, 0, claude='working'), [])
        self.assertEqual(self.tick(daemon, 1, claude='waiting', **{'claude.message': 'Allow Bash?'}), [('Claude Code', 'Allow Bash?')])
        self.assertEqual(len(self.tick(daemon, 2, claude='waiting', **{'claude.message': 'Allow Bash?'})), 1, 'not again')

    def test_long_work_that_ends_is_announced_and_a_short_burst_is_not(self):
        daemon = self.daemon()
        self.tick(daemon, 0, codex='working')
        self.assertEqual(self.tick(daemon, 10, codex='idle'), [])
        self.tick(daemon, 20, codex='working')
        self.assertEqual(self.tick(daemon, 100, codex='idle', **{'codex.project': 'app'}), [('Codex', 'Finished in app')])

    @unittest.skipIf(importlib.util.find_spec('pystray') is None, 'pystray is not installed')
    def test_the_tray_names_who_is_waiting(self):
        import tessera_tray
        status = {'running': True, 'device': {'connected': True, 'port': 'COM4', 'profile': 'main', 'page': 'main'},
                  'agent_states': {'claude': 'waiting', 'codex': 'working'}}
        self.assertTrue(tessera_tray.status_text(status).endswith('Claude waiting for you'))
        status['agent_states'] = {}
        self.assertFalse(tessera_tray.status_text(status).endswith('waiting for you'))


if __name__ == '__main__':
    unittest.main()
