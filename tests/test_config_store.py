"""Schema versioning, migration and rotating backups with restore."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import config_store
import tesserad as deck
from tessera_app import Editor


def config(label='Copy'):
    return {'default_profile': 'Main', 'profiles': {'Main': {'match': [], 'pages': {
        'First': [{'id': 1, 'label': label, 'icon': 'ok', 'actions': [{'type': 'hotkey', 'keys': 'ctrl+c'}]}]}}}}


class Clock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class VersionTests(unittest.TestCase):
    def test_old_files_are_migrated_and_stamped_without_touching_the_original(self):
        original = config()
        migrated = config_store.migrate(original)
        self.assertEqual(migrated['version'], config_store.CONFIG_VERSION)
        self.assertNotIn('version', original)
        self.assertEqual(migrated['profiles'], original['profiles'])

    def test_a_file_from_a_newer_tessera_is_refused_clearly(self):
        with self.assertRaises(config_store.FutureConfig) as raised:
            config_store.migrate(dict(config(), version=config_store.CONFIG_VERSION + 1))
        self.assertIn('Update Tessera', str(raised.exception))
        with self.assertRaises(ValueError):
            deck.validate_config(dict(config(), version=config_store.CONFIG_VERSION + 1))

    def test_a_malformed_version_is_rejected(self):
        for bad in (0, -1, '2', 1.5, None, True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                config_store.migrate(dict(config(), version=bad))

    def test_the_host_loads_an_unversioned_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'profiles.json'
            path.write_text(json.dumps(config()))
            self.assertEqual(deck.Daemon.load_profiles(path)['version'], config_store.CONFIG_VERSION)

    def test_the_bundled_default_profiles_migrate_and_validate(self):
        defaults = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        deck.validate_config(config_store.migrate(defaults))


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'profiles.json'
        self.clock = Clock()

    def write(self, label):
        self.path.write_text(json.dumps(config(label)))

    def backup(self, **kwargs):
        made = config_store.backup(self.path, now=self.clock, **kwargs)
        if made:
            os.utime(made, (self.clock.now, self.clock.now))
        return made

    def test_the_first_save_makes_a_backup_and_frequent_saves_do_not_flood_the_folder(self):
        self.write('one')
        first = self.backup()
        self.assertIsNotNone(first)
        self.clock.now += 60
        self.write('two')
        self.assertIsNone(self.backup(), 'a backup less than ten minutes old is enough')
        self.clock.now += 601
        self.assertIsNotNone(self.backup())
        self.assertEqual(len(list(first.parent.glob('profiles-*.json'))), 2)

    def test_an_unchanged_file_is_not_backed_up_twice(self):
        self.write('same')
        self.assertIsNotNone(self.backup())
        self.clock.now += 5000
        self.assertIsNone(self.backup())

    def test_force_always_backs_up_and_names_never_collide(self):
        self.write('one')
        names = {self.backup(force=True).name for _ in range(3)}
        self.assertEqual(len(names), 3)

    def test_only_the_newest_backups_are_kept(self):
        for number in range(6):
            self.write(f'v{number}')
            self.clock.now += 1000
            self.backup(keep=3)
        kept = config_store.list_backups(self.path)
        self.assertEqual(len(kept), 3)
        self.assertEqual([item['buttons'] for item in kept], [1, 1, 1])

    def test_listing_describes_each_backup_and_skips_damaged_or_foreign_files(self):
        self.write('one')
        self.backup()
        folder = config_store.backups_dir(self.path)
        (folder / 'profiles-20200101-000000.json').write_text('not json')
        (folder / 'notes.txt').write_text('hello')
        listing = config_store.list_backups(self.path)
        self.assertEqual(len(listing), 1)
        self.assertEqual((listing[0]['profiles'], listing[0]['buttons'], listing[0]['version']), (1, 1, 1))

    def test_reading_a_backup_validates_the_name_and_migrates(self):
        self.write('one')
        name = self.backup().name
        self.assertEqual(config_store.read_backup(self.path, name)['version'], config_store.CONFIG_VERSION)
        for bad in ('../profiles.json', 'profiles-1.json', 'x', None, 5):
            with self.assertRaises(ValueError):
                config_store.read_backup(self.path, bad)
        with self.assertRaises(ValueError):
            config_store.read_backup(self.path, 'profiles-20990101-000000.json')

    def test_a_missing_file_has_nothing_to_back_up(self):
        self.assertIsNone(self.backup())


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'profiles.json'
        self.path.write_text(json.dumps(config('original')))
        self.editor = Editor(self.path, dashboard=lambda: {'running': False, 'device': {}})

    def test_saving_backs_up_the_previous_file_and_a_backup_can_be_restored(self):
        state = self.editor.read()
        changed = json.loads(json.dumps(state['config']))
        changed['profiles']['Main']['pages']['First'][0]['label'] = 'changed'
        saved = self.editor.save({'config': changed, 'revision': state['revision']})
        listing = self.editor.command('backups', {})['backups']
        self.assertEqual(len(listing), 1)
        restored = self.editor.command('restore-backup', {'name': listing[0]['name']})
        self.assertEqual(restored['config']['profiles']['Main']['pages']['First'][0]['label'], 'original')
        self.assertNotEqual(restored['revision'], saved['revision'])
        again = self.editor.command('backups', {})['backups']
        self.assertEqual(len(again), 2, 'restoring keeps the configuration it replaced')

    def test_restoring_something_invalid_changes_nothing(self):
        state = self.editor.read()
        folder = config_store.backups_dir(self.path)
        folder.mkdir()
        (folder / 'profiles-20200101-000000.json').write_text(json.dumps({'profiles': {}}))
        with self.assertRaises(ValueError):
            self.editor.command('restore-backup', {'name': 'profiles-20200101-000000.json'})
        self.assertEqual(self.editor.read()['revision'], state['revision'])
        with self.assertRaises(ValueError):
            self.editor.command('restore-backup', {'name': '../../etc/passwd'})


if __name__ == '__main__':
    unittest.main()
