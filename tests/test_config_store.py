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

    def test_write_atomic_replaces_the_file_and_leaves_no_temporary_files(self):
        from unittest.mock import patch
        from deck_control import save_profiles
        save_profiles(config('one'), self.path)
        save_profiles(config('two'), self.path)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), config('two'))
        with patch('config_store.os.replace', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                config_store.write_atomic(self.path, b'{}')
        self.assertEqual([file.name for file in self.path.parent.iterdir()], ['profiles.json'])
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), config('two'))

    def test_newest_and_pruning_follow_the_time_written_not_the_name(self):
        folder = config_store.backups_dir(self.path)
        folder.mkdir()
        # By name '-1' and '-10' sort before the base copy and '-2'; a foreign 'profiles-old.json' sorts last.
        for age, name in enumerate(('profiles-20300101-120000.json', 'profiles-20300101-120000-1.json',
                                    'profiles-20300101-120000-2.json', 'profiles-20300101-120000-10.json')):
            (folder / name).write_text(json.dumps(config(name)))
            os.utime(folder / name, (self.clock.now - 4000 + age, self.clock.now - 4000 + age))
        (folder / 'profiles-old.json').write_text(json.dumps(config('mine')))
        os.utime(folder / 'profiles-old.json', (self.clock.now - 1, self.clock.now - 1))
        self.write('profiles-20300101-120000-10.json')
        self.assertIsNone(self.backup(), 'the newest copy (-10) already holds these bytes')
        self.write('fresh')
        made = self.backup(force=True, keep=2)
        left = sorted(file.name for file in folder.glob('profiles-*.json'))
        self.assertEqual(left, sorted([made.name, 'profiles-20300101-120000-10.json', 'profiles-old.json']))
        self.assertEqual(config_store.list_backups(self.path)[0]['name'], made.name)

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

    def test_setup_flags_keep_only_known_keys_of_the_right_type(self):
        self.editor.command('setup-done', {'firmware_hint_dismissed': '0.7.0'})
        self.assertEqual(self.editor.command('setup-state', {})['firmware_hint_dismissed'], '0.7.0')
        for wrong in ({'welcome_done': 'yes'}, {'other': 1}):
            with self.assertRaises(ValueError):
                self.editor.command('setup-done', wrong)
        (self.path.with_name('setup.local.json')).write_text('[1]')
        self.assertNotIn('firmware_hint_dismissed', self.editor.command('setup-state', {}))

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

    def test_the_tray_notification_switch_does_not_conflict_with_the_editor(self):
        from tessera_tray import set_notifications
        state = self.editor.read()
        changed = json.loads(json.dumps(state['config']))
        changed['profiles']['Main']['pages']['First'][0]['label'] = 'changed'
        set_notifications(False, self.path)  # the tray menu, while the editor is open
        saved = self.editor.save({'config': changed, 'revision': state['revision']})
        self.assertEqual(saved['config']['profiles']['Main']['pages']['First'][0]['label'], 'changed')
        self.assertIs(saved['config']['notifications'], False, 'the tray switch stays')
        mine = json.loads(json.dumps(saved['config']))
        mine['notifications'] = True  # switched back on in Program settings: the editor's choice wins
        again = self.editor.save({'config': mine, 'revision': saved['revision']})
        self.assertIs(again['config']['notifications'], True)

    def test_a_tray_brightness_change_does_not_conflict_with_the_editor(self):
        from tessera_app import Conflict
        from tessera_tray import set_brightness
        state = self.editor.read()
        changed = json.loads(json.dumps(state['config']))
        changed['profiles']['Main']['pages']['First'][0]['label'] = 'changed'
        set_brightness(40, self.path)  # the tray's Brightness menu, while the editor is open
        saved = self.editor.save({'config': changed, 'revision': state['revision']})
        self.assertEqual(saved['config']['profiles']['Main']['pages']['First'][0]['label'], 'changed')
        self.assertEqual(saved['config']['display']['brightness'], 40, 'the tray level stays')
        on_disk = json.loads(self.path.read_text(encoding='utf-8'))
        on_disk['profiles']['Main']['pages']['First'][0]['label'] = 'elsewhere'
        self.path.write_text(json.dumps(on_disk), encoding='utf-8')  # any other change still conflicts
        with self.assertRaises(Conflict):
            self.editor.save({'config': changed, 'revision': saved['revision']})

    def test_a_backup_can_be_restored_over_a_broken_file_which_is_kept(self):
        state = self.editor.read()
        changed = json.loads(json.dumps(state['config']))
        changed['profiles']['Main']['pages']['First'][0]['label'] = 'changed'
        self.editor.save({'config': changed, 'revision': state['revision']})
        name = self.editor.command('backups', {})['backups'][0]['name']
        for broken in (b'{"profiles": ', json.dumps(dict(config(), version=99)).encode()):
            with self.subTest(broken=broken[:20]):
                self.path.write_bytes(broken)
                opened = self.editor.read_for_editor()
                self.assertIn('error', opened)
                self.assertTrue(opened['config']['profiles'])
                with self.assertRaises(ValueError):  # a normal save must not overwrite the broken file
                    self.editor.save({'config': opened['config'], 'revision': opened['revision']})
                self.assertEqual(self.path.read_bytes(), broken)
                restored = self.editor.command('restore-backup', {'name': name})
                self.assertEqual(restored['config']['profiles']['Main']['pages']['First'][0]['label'], 'original')
                self.assertEqual(self.path.with_name('profiles-previous.local.json').read_bytes(), broken)

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

    def test_run_now_needs_a_valid_key_and_a_connected_panel(self):
        config = self.editor.read()['config']
        profile = next(iter(config['profiles']))
        page = next(iter(config['profiles'][profile]['pages']))
        with self.assertRaisesRegex(ValueError, 'from 1 to 18'):
            self.editor.command('run-key', {'profile': profile, 'page': page, 'button': 19})
        with self.assertRaisesRegex(ValueError, 'Connect the panel'):  # a press must not wait for a host started later
            self.editor.command('run-key', {'profile': profile, 'page': page, 'button': 1})


if __name__ == '__main__':
    unittest.main()
