"""Connecting Claude Code: Tessera's hooks are added and removed without touching anything else."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import adapters
import claude_setup

PYTHON, DECKCTL = Path('C:/py/python.exe'), Path('C:/tessera/host/deckctl.py')
OTHER = {'matcher': '*', 'hooks': [{'type': 'command', 'command': 'other-tool --log'}]}


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        (self.home / '.claude').mkdir()
        self.file = self.home / '.claude' / 'settings.json'

    def write(self, document):
        self.file.write_text(json.dumps(document), encoding='utf-8')

    def update(self, events, allow):
        return claude_setup.update(events, allow, PYTHON, DECKCTL, self.home)

    def test_both_parts_are_installed_and_other_hooks_and_settings_stay(self):
        self.write({'model': 'opus', 'hooks': {'PreToolUse': [OTHER], 'Stop': [OTHER]}})
        self.assertEqual(self.update(True, True), {'events': True, 'permission': True})
        document = json.loads(self.file.read_text(encoding='utf-8'))
        self.assertEqual(document['model'], 'opus')
        self.assertIn(OTHER, document['hooks']['PreToolUse'])
        self.assertEqual(len(document['hooks']['PreToolUse']), 2)
        command = document['hooks']['PermissionRequest'][0]['hooks'][0]
        self.assertTrue(command['command'].endswith('deckctl.py" permission'))
        self.assertGreater(command['timeout'], 25)

    def test_running_it_twice_changes_nothing_and_removing_restores_the_original(self):
        original = {'hooks': {'PreToolUse': [OTHER]}}
        self.write(original)
        self.update(True, True)
        once = self.file.read_text(encoding='utf-8')
        self.update(True, True)
        self.assertEqual(self.file.read_text(encoding='utf-8'), once)
        self.assertEqual(self.update(False, False), {'events': False, 'permission': False})
        self.assertEqual(json.loads(self.file.read_text(encoding='utf-8')), original)

    def test_the_parts_are_independent(self):
        self.assertEqual(self.update(False, True), {'events': False, 'permission': True})
        self.assertEqual(self.update(True, False), {'events': True, 'permission': False})
        self.assertEqual(claude_setup.state(self.home), {'events': True, 'permission': False})

    def test_a_backup_is_kept_and_an_unreadable_file_is_never_touched(self):
        self.write({'hooks': {}})
        self.update(True, False)
        self.assertTrue(list((self.home / '.claude').glob('settings.tessera-backup-*.json')))
        self.file.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.update(True, True)
        self.assertEqual(self.file.read_text(encoding='utf-8'), '{broken')

    def test_two_changes_in_the_same_second_keep_the_original_in_a_backup(self):
        original = {'model': 'opus'}
        self.write(original)
        with patch.object(claude_setup.time, 'strftime', return_value='20260101-120000'):
            self.update(True, False)
            self.update(True, True)
        backups = sorted((self.home / '.claude').glob('settings.tessera-backup-*.json'))
        self.assertEqual(len(backups), 2)
        self.assertIn(original, [json.loads(item.read_text(encoding='utf-8')) for item in backups])

    def test_a_missing_file_is_created_and_the_events_cover_what_the_adapter_reads(self):
        self.assertEqual(claude_setup.state(self.home), {'events': False, 'permission': False})
        self.update(True, False)
        hooks = json.loads(self.file.read_text(encoding='utf-8'))['hooks']
        self.assertEqual(set(hooks), set(adapters.CLAUDE_EVENTS))


if __name__ == '__main__':
    unittest.main()
