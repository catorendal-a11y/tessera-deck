"""A notice when an agent starts waiting for you or finishes long work, and the tray says who waits."""
import importlib.util
from pathlib import Path
import sys
import unittest
import unittest.mock

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

    def test_a_quiet_file_during_long_work_is_not_finished_until_it_stays_quiet(self):
        daemon = self.daemon()

        def look(now, state):  # no hook: only the session file says what the tool does
            daemon.custom_vars.clear()
            daemon.activity.read = lambda: {'codex': {'state': state, 'project': 'app', 'age': 0 if state == 'working' else 20, 'tool': ''}}
            daemon.agent_notice_tick(now)
            return [notice['message'] for notice in daemon.notices]

        look(0, 'working')
        self.assertEqual(look(70, 'idle'), [], 'a long test run writes nothing for a while')
        self.assertEqual(look(100, 'idle'), [])
        look(105, 'working')                       # it was still at work
        self.assertEqual(look(130, 'idle'), [])
        self.assertEqual(look(174, 'idle'), [])
        self.assertEqual(look(175, 'idle'), ['Finished in app'], 'idle for 45 s: done, timed from the first start')
        self.assertEqual(look(300, 'idle'), ['Finished in app'], 'once')

    @unittest.skipIf(importlib.util.find_spec('pystray') is None, 'pystray is not installed')
    def test_the_tray_names_who_is_waiting(self):
        import tessera_tray
        status = {'running': True, 'device': {'connected': True, 'port': 'COM4', 'profile': 'main', 'page': 'main'},
                  'agent_states': {'claude': 'waiting', 'codex': 'working'}}
        self.assertTrue(tessera_tray.status_text(status).endswith('Claude waiting for you'))
        status['agent_states'] = {}
        self.assertFalse(tessera_tray.status_text(status).endswith('waiting for you'))


    @unittest.skipIf(importlib.util.find_spec('pystray') is None, 'pystray is not installed')
    def test_the_tray_menu_follows_the_status_and_starts_one_host(self):
        import threading
        import time
        from unittest.mock import Mock
        import tessera_tray
        controller = Mock()
        controller.status.return_value = {'running': False}
        app = tessera_tray.TrayApp(controller)
        app.icon = Mock()
        app.refresh()
        app.refresh()
        self.assertEqual(app.icon.update_menu.call_count, 1, 'an unchanged status does not rebuild the menu')
        controller.status.return_value = {'running': True, 'device': {'connected': True, 'port': 'COM4', 'profile': 'main', 'page': 'main'}}
        app.refresh()
        self.assertEqual(app.icon.update_menu.call_count, 2, 'a new status rebuilds it')
        self.assertLessEqual(len(app.icon.title), 120)

        release, running = threading.Event(), threading.Event()
        controller.start.side_effect = lambda **_: (running.set(), release.wait(5))
        app.start_host()
        self.assertTrue(running.wait(5))
        app.start_host()                      # a second click while the first start is still running
        app.restart_host()
        time.sleep(0.2)
        release.set()
        time.sleep(0.2)
        self.assertEqual(controller.start.call_count, 1)
        controller.stop.assert_not_called()

        app.open_editor = tessera_tray.TrayApp.open_editor.__get__(app)
        with unittest.mock.patch.object(tessera_tray.subprocess, 'Popen') as popen:
            app.open_editor()
            app.open_editor()                 # the second half of a double click
        self.assertEqual(popen.call_count, 1)

    @unittest.skipIf(importlib.util.find_spec('pystray') is None, 'pystray is not installed')
    def test_the_tray_reports_a_lasting_problem_once_and_shows_the_versions(self):
        from unittest.mock import Mock
        import tessera_tray
        status = {'running': True, 'device': {'connected': False, 'error': 'COM4 is used by another program', 'firmware': '0.6.2'}}
        self.assertIn('panel 0.6.2', tessera_tray.version_text(status))
        app = tessera_tray.TrayApp(Mock())
        app.icon, app.status = Mock(), status
        text = tessera_tray.trouble_text(status)
        app.report_trouble(text, 100.0)
        app.report_trouble(text, 110.0)
        app.icon.notify.assert_not_called()  # a short hiccup is no news
        app.report_trouble(text, 131.0)
        app.report_trouble(text, 200.0)
        app.icon.notify.assert_called_once()
        self.assertIn('another program', app.icon.notify.call_args.args[0])
        app.status = {'running': False}
        app.user_stopped = True
        app.report_trouble(tessera_tray.trouble_text(app.status), 300.0)
        app.report_trouble(tessera_tray.trouble_text(app.status), 400.0)
        self.assertEqual(app.icon.notify.call_count, 1, 'a host the user stopped is not reported')
        self.assertIsNone(tessera_tray.trouble_text({'running': True, 'device': {'connected': True}}))

    @unittest.skipIf(importlib.util.find_spec('pystray') is None, 'pystray is not installed')
    def test_the_tray_keeps_quiet_and_offers_no_start_while_the_firmware_is_installed(self):
        from unittest.mock import Mock
        import tessera_tray
        app = tessera_tray.TrayApp(Mock())
        app.icon, app.status = Mock(), {'running': False}
        with unittest.mock.patch.object(tessera_tray, 'firmware_installing', return_value=True):
            for now in (100.0, 200.0):
                app.report_trouble(tessera_tray.trouble_text(app.status), now)
            items = {item.text: item for item in app.menu_items()}
        app.icon.notify.assert_not_called()
        self.assertFalse(items['Start host'].enabled)
        self.assertIn('Installing panel firmware …', items)

    def test_a_firmware_flag_blocks_a_host_start_until_it_expires(self):
        import os
        import tempfile
        import time
        import deck_control
        with tempfile.TemporaryDirectory() as folder:
            flag = Path(folder) / 'flag.json'
            self.assertFalse(deck_control.firmware_installing(flag))
            flag.write_text('{}')
            self.assertTrue(deck_control.firmware_installing(flag))
            old = time.time() - deck_control.FIRMWARE_FLAG_SECONDS - 1
            os.utime(flag, (old, old))
            self.assertFalse(deck_control.firmware_installing(flag), 'a flag left by a crashed editor expires')
            with unittest.mock.patch.object(deck_control, 'firmware_installing', return_value=True),                     self.assertRaises(RuntimeError):
                deck_control.Controller().start()

if __name__ == '__main__':
    unittest.main()
