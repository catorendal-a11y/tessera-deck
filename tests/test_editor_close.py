"""Closing the editor: unsaved edits and unfinished keys must not vanish without a question (audit p1-32, p1-33), and a firmware install that is running (p1-20)."""
import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tessera_app
import test_editor
from test_editor import run_editor

# The page's own listeners are kept, so a test can fire the beforeunload the browser would fire.
CATCH = "const listeners = {}; const context = vm.createContext({listeners, document, window: Object.assign(stub(), {addEventListener: (type, fn) => (listeners[type] ||= []).push(fn)}),"
HARNESS = test_editor.EDITOR_HARNESS.replace('const context = vm.createContext({document, window: stub(),', CATCH)
assert HARNESS != test_editor.EDITOR_HARNESS


def run_page(test, script):
    with patch.object(test_editor, 'EDITOR_HARNESS', HARNESS):
        return run_editor(test, script)


PAGE = '''
config = {default_profile: 'Main', profiles: {Main: {match: [], pages: {First: [
  {id: 1, label: 'Copy', icon: 'ok', actions: [{type: 'hotkey', keys: 'ctrl+c'}]}]}}}};
profile = 'Main'; page = 'First'; savedBase = clone(config); revision = 'r1'; dirty = false;
const asked = () => { const event = {prevented: false, preventDefault() { this.prevented = true; }}; listeners.beforeunload.forEach(fn => fn(event)); return event.prevented; };
'''


class UnloadTests(unittest.TestCase):
    def test_leaving_warns_while_a_key_is_an_unfinished_draft(self):
        found = run_page(self, PAGE + '''
const clean = asked();
config.profiles.Main.pages.First[0].label = '';   // the name is cleared: the last save left the key out, so nothing is dirty
const nameless = asked();
config.profiles.Main.pages.First[0].label = 'Open';
config.profiles.Main.pages.First[0].actions = [{type: 'open', target: ''}];
return {clean, nameless, noTarget: asked()};
''')
        self.assertEqual(found, {'clean': False, 'nameless': True, 'noTarget': True})

    def test_closing_the_window_sends_the_edit_that_is_waiting(self):
        found = run_page(self, PAGE + '''
const sent = [];
api = async (path, data) => { sent.push(data.config.profiles.Main.pages.First[0].label); return {revision: 'r2'}; };
config.profiles.Main.pages.First[0].label = 'Renamed'; changed();   // the 650 ms timer has not fired
const unsaved = await flushBeforeClose();
return {unsaved, sent};
''')
        self.assertEqual(found, {'unsaved': False, 'sent': ['Renamed']})

    def test_closing_the_window_reports_a_save_that_failed(self):
        found = run_page(self, PAGE + '''
api = async () => { throw new Error('The PC did not answer'); };
toast = () => {};
config.profiles.Main.pages.First[0].label = 'Renamed'; changed();
return await flushBeforeClose();
''')
        self.assertIs(found, True)


class FakeWindow:
    """pywebview's window as far as the close path sees it: the page answers evaluate_js, destroy ends the window."""
    def __init__(self, unsaved):
        self.unsaved, self.destroyed, self.asked, self.scripts = unsaved, threading.Event(), [], []
        self.events = types.SimpleNamespace(closing=Handlers(), resized=Handlers(), moved=Handlers(), shown=threading.Event())

    def evaluate_js(self, script, callback=None):
        self.scripts.append(script)
        threading.Thread(target=callback, args=(self.unsaved,)).start()
        return 'true'

    def create_confirmation_dialog(self, title, message):
        self.asked.append(message)
        return self.answer

    def destroy(self):
        self.destroyed.set()


class Handlers:
    def __init__(self):
        self.items = []

    def __iadd__(self, fn):
        self.items.append(fn)
        return self

    def fire(self):
        return any(fn() is False for fn in self.items)


class WindowCloseTests(unittest.TestCase):
    def close_with(self, unsaved, answer=True):
        from platform_windows import editor_window
        window = FakeWindow(unsaved)
        window.answer = answer
        outcome = {}

        def start(*args, **kwargs):
            outcome['cancelled'] = window.events.closing.fire()
            outcome['closed'] = window.destroyed.wait(2)
        fake = types.SimpleNamespace(settings={}, screens=[types.SimpleNamespace(width=1920, height=1080)],
                                     create_window=lambda *a, **k: window, start=start)
        saved = []
        with patch.dict(sys.modules, {'webview': fake}), patch('os.name', 'nt'), patch.object(editor_window, 'brand_taskbar_identity'):
            editor_window.open_native_window('http://127.0.0.1:1/', lambda screen: (900, 700, None, None), saved.append, (1050, 640), ROOT)
        return window, outcome

    def test_the_window_asks_the_page_before_it_closes(self):
        window, outcome = self.close_with(unsaved=False)
        self.assertEqual(window.scripts, ['flushBeforeClose()'])
        self.assertTrue(outcome['cancelled'])  # the close is held until the page has answered
        self.assertTrue(outcome['closed'])
        self.assertEqual(window.asked, [])

    def test_unsaved_work_is_asked_about_and_the_window_stays_on_no(self):
        window, outcome = self.close_with(unsaved=True, answer=False)
        self.assertEqual(len(window.asked), 1)
        self.assertFalse(outcome['closed'])

    def test_unsaved_work_is_dropped_only_on_yes(self):
        window, outcome = self.close_with(unsaved=True, answer=True)
        self.assertEqual(len(window.asked), 1)
        self.assertTrue(outcome['closed'])


class FirmwareInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profiles = Path(self.temp.name) / 'profiles.json'
        self.profiles.write_text(json.dumps({'default_profile': 'Main', 'profiles': {'Main': {'match': [], 'pages': {'First': []}}}}))

    def test_the_program_update_is_refused_while_the_panel_firmware_is_installing(self):
        editor = tessera_app.Editor(self.profiles, dashboard=lambda: {'running': False, 'device': {}})
        editor.last_release = {'newer': True, 'latest': '9.9.9'}
        editor.firmware_lock.acquire()
        self.addCleanup(editor.firmware_lock.release)
        with patch('updates.download_host') as download, patch.object(tessera_app.Editor, 'restart_soon') as restart:
            with self.assertRaises(ValueError) as raised:
                editor.install_host_update()
        download.assert_not_called()  # the restart would cut esptool off mid-write
        restart.assert_not_called()
        self.assertIn('firmware', str(raised.exception))

    def test_closing_the_window_waits_for_a_running_firmware_install(self):
        servers, install, real = [], {}, tessera_app.make_server

        def make_server(*args, **kwargs):
            servers.append(real(*args, **kwargs))
            return servers[-1]

        def window(launch_url):
            # the install is running when the window closes, and ends a second and a half later
            lock = servers[0].editor.firmware_lock
            lock.acquire()
            install['lock'] = lock
            threading.Timer(1.5, lock.release).start()
            return True
        with patch.object(sys, 'argv', ['tessera_app.py', '--profiles', str(self.profiles)]),                 patch.object(tessera_app, 'make_server', make_server), patch.object(tessera_app, 'open_window', window):
            tessera_app.main()
        self.assertFalse(install['lock'].locked(), 'the editor ended while the install still ran')


if __name__ == '__main__':
    unittest.main()
