"""Closing the editor: unsaved edits and unfinished keys must not vanish without a question (audit p1-33)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
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


if __name__ == '__main__':
    unittest.main()
