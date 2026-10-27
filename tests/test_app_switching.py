"""Switching profiles by the program in front: shell surfaces are ignored, the view you left is restored, Store apps match."""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck


def context(exe, title=''):
    return {'exe': exe, 'title': title.lower(), 'processes': [exe]}


class NeutralWindowTests(unittest.TestCase):
    def test_shell_surfaces_and_tessera_itself_are_neutral(self):
        for exe, title in (('searchhost.exe', 'search'), ('startmenuexperiencehost.exe', 'start'),
                           ('shellexperiencehost.exe', 'new notification'), ('lockapp.exe', ''),
                           ('explorer.exe', ''), ('explorer.exe', 'Task Switching'),
                           ('pythonw.exe', 'Tessera · main / main'), ('msedgewebview2.exe', 'Tessera')):
            with self.subTest(exe=exe, title=title):
                self.assertTrue(deck.is_neutral_window(context(exe, title)))

    def test_real_programs_are_not_neutral(self):
        for exe, title in (('explorer.exe', 'Documents'), ('pythonw.exe', 'my script'), ('chrome.exe', 'Tessera docs'),
                           ('code.exe', '')):
            with self.subTest(exe=exe, title=title):
                self.assertFalse(deck.is_neutral_window(context(exe, title)))


class StoreAppTests(unittest.TestCase):
    def test_a_frame_host_window_is_the_app_inside_it(self):
        self.assertEqual(deck.real_app_exe('applicationframehost.exe', ['applicationframehost.exe', '', 'calculatorapp.exe']),
                         'calculatorapp.exe')

    def test_a_frame_host_without_a_visible_app_stays_the_frame_host(self):
        self.assertEqual(deck.real_app_exe('applicationframehost.exe', ['applicationframehost.exe']),
                         'applicationframehost.exe')

    def test_other_programs_are_left_alone(self):
        self.assertEqual(deck.real_app_exe('chrome.exe', ['chrome.exe', 'other.exe']), 'chrome.exe')


class SwitchingTests(unittest.TestCase):
    def make_daemon(self):
        daemon = deck.Daemon(types.SimpleNamespace(profiles=str(ROOT / 'host/profiles.default.json'), port='TEST',
                                                   verbose=False, no_focus=False, deck_only=True))
        daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
        daemon.panel.push_buttons = Mock()
        daemon.config['profiles']['coding']['match'] = ['code.exe']
        return daemon

    def tick(self, daemon, shown):
        with patch.object(deck, 'foreground_context', return_value=shown):
            daemon.focus_tick()
        while not daemon.jobs.empty():
            daemon.handle_job(daemon.jobs.get_nowait())

    def test_a_neutral_window_does_not_end_an_automatic_switch(self):
        daemon = self.make_daemon()
        self.tick(daemon, context('code.exe', 'editor'))
        self.assertEqual(daemon.profile, 'coding')
        for shell in (context('explorer.exe', 'Task Switching'), context('searchhost.exe', 'Search')):
            self.tick(daemon, shell)
            self.assertEqual((daemon.profile, daemon.auto_profile), ('coding', 'coding'))
        self.tick(daemon, context('notepad.exe', 'Notepad'))
        self.assertEqual(daemon.profile, 'main')

    def test_the_page_and_folder_you_left_come_back_with_the_profile(self):
        daemon = self.make_daemon()
        daemon.profile, daemon.page, daemon.folder_stack = 'main', 'system', ['main']
        self.tick(daemon, context('code.exe', 'editor'))
        self.assertEqual((daemon.profile, daemon.page), ('coding', 'main'))
        self.tick(daemon, context('notepad.exe', 'Notepad'))
        self.assertEqual((daemon.profile, daemon.page, daemon.folder_stack), ('main', 'system', ['main']))

    def test_a_page_that_no_longer_exists_falls_back_to_the_first_page(self):
        daemon = self.make_daemon()
        daemon.profile, daemon.page = 'main', 'system'
        self.tick(daemon, context('code.exe', 'editor'))
        del daemon.config['profiles']['main']['pages']['system']
        self.tick(daemon, context('notepad.exe', 'Notepad'))
        self.assertEqual((daemon.profile, daemon.page), ('main', 'main'))

    def test_the_remembered_view_is_used_once(self):
        daemon = self.make_daemon()
        daemon.profile, daemon.page = 'main', 'system'
        self.tick(daemon, context('code.exe', 'editor'))
        self.tick(daemon, context('notepad.exe', 'Notepad'))
        daemon.switch_profile('coding')  # a manual switch afterwards
        daemon.switch_profile('main')
        self.assertEqual(daemon.page, 'main')


if __name__ == '__main__':
    unittest.main()
