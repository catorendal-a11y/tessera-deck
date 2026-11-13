"""The host keeps going on its own: restarts after a crash, rotated logs, recent problems, safe backups."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import config_store  # noqa: E402
import diagnostics  # noqa: E402
import host_support  # noqa: E402
import tesserad  # noqa: E402
import updates  # noqa: E402
from action_runner import CommandFailed  # noqa: E402
from import_review import review  # noqa: E402


def config(label='Copy'):
    return {'default_profile': 'Main', 'profiles': {'Main': {'match': [], 'pages': {
        'First': [{'id': 1, 'label': label, 'icon': 'ok', 'actions': [{'type': 'hotkey', 'keys': 'ctrl+c'}]}]}}}}


class LogTests(unittest.TestCase):
    def test_three_older_logs_are_kept_while_the_host_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'deck.local.log'
            for round_ in range(5):
                with path.open('w', encoding='utf-8') as log:
                    log.write(f'round {round_} ' * 5)
                    log.flush()
                    with patch.object(tesserad, 'LOG_PATH', path), patch.object(tesserad, 'LOG_KEEP_BYTES', 10), \
                            patch.object(tesserad.sys, 'stdout', log):
                        tesserad.rotate_log()
            names = sorted(file.name for file in Path(folder).iterdir())
            self.assertEqual(names, ['deck.local.log', 'deck.local.log.1', 'deck.local.log.2', 'deck.local.log.3'])
            self.assertTrue(path.with_name('deck.local.log.1').read_text(encoding='utf-8').startswith('round 4'))
            self.assertTrue(path.with_name('deck.local.log.3').read_text(encoding='utf-8').startswith('round 2'))

    def test_recent_problems_are_the_last_failures_from_both_logs_and_go_into_diagnostics(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'deck.local.log'
            path.with_name('deck.local.log.1').write_text('[1] Action failed: old\n[2] fine\n', encoding='utf-8')
            lines = [f'[{n}] Action failed: C:\\Users\\Someone\\x {n}' for n in range(30)] + ['[99] Panel connected']
            path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            problems = diagnostics.recent_problems(path)
            self.assertEqual(len(problems), 20)
            self.assertTrue(problems[-1].startswith('[29]'))
            self.assertNotIn('Someone', '\n'.join(problems))
            self.assertEqual(diagnostics.recent_problems(path, 40)[0], '[1] Action failed: old')
            self.assertEqual(diagnostics.recent_problems(Path(folder) / 'missing.log'), [])
            target = diagnostics.build(Path(folder) / 'out', config(), {}, '0.6.3', path)
            import zipfile
            with zipfile.ZipFile(target) as archive:
                report = json.loads(archive.read('report.json'))
            self.assertEqual(len(report['recent_problems']), 20)


class HttpTests(unittest.TestCase):
    def test_an_error_status_fails_the_action_with_its_code(self):
        daemon = host_support.test_daemon(port='TEST', no_focus=True)
        daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
        daemon.stop.clear()
        error = tesserad.urllib.error.HTTPError('https://example.com/x', 503, 'Service Unavailable', {}, None)
        with patch.object(tesserad.urllib.request, 'urlopen', Mock(side_effect=error)):
            with self.assertRaisesRegex(CommandFailed, 'HTTP 503 Service Unavailable'):
                daemon.run_action({'type': 'http', 'url': 'https://example.com/x'})
        with patch.object(tesserad.urllib.request, 'urlopen', MagicMock()):
            daemon.run_action({'type': 'http', 'url': 'https://example.com/x'})  # a good answer passes

    def test_the_import_review_names_the_host_each_request_goes_to(self):
        long_path = 'a' * 300
        bundle = config()
        bundle['profiles']['Main']['pages']['First'][0]['actions'] = [
            {'type': 'http', 'url': f'https://hooks.example.net/{long_path}'},
            {'type': 'http', 'url': '$(var:base)/hook'}]
        details = [item['detail'] for item in review(bundle)]
        self.assertIn('(host hooks.example.net)', details[0])
        self.assertIn('host set when it runs', details[1])


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'profiles.json'
        self.now = 1_800_000_000.0

    def backup(self, text):
        self.path.write_text(text, encoding='utf-8')
        self.now += 1000
        made = config_store.backup(self.path, now=lambda: self.now)
        if made:
            os.utime(made, (self.now, self.now))
        return made

    def test_an_invalid_file_is_never_backed_up_so_good_copies_stay(self):
        for number in range(3):
            self.assertIsNotNone(self.backup(json.dumps(config(f'good {number}'))))
        for bad in ('{not json', json.dumps({'profiles': 'x'}), '\xff'):
            self.assertIsNone(self.backup(bad))
        self.assertEqual([item['buttons'] for item in config_store.list_backups(self.path)], [1, 1, 1])
        self.assertEqual(len(config_store.list_backups(self.path)), 3)

    def test_a_broken_file_is_replaced_by_the_newest_good_backup_on_start(self):
        self.backup(json.dumps(config('older')))
        self.backup(json.dumps(config('newest')))
        folder = config_store.backups_dir(self.path)
        damaged = folder / 'profiles-20990101-000000.json'  # newest by time, but unusable
        damaged.write_text('{"profiles": 1}', encoding='utf-8')
        os.utime(damaged, (self.now + 10, self.now + 10))
        self.path.write_text('{broken', encoding='utf-8')
        restored = config_store.recover(self.path)
        self.assertNotEqual(restored, damaged.name)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['profiles']['Main']['pages']['First'][0]['label'],
                         'newest')
        self.assertEqual(self.path.with_name('profiles-unreadable.local.json').read_text(encoding='utf-8'), '{broken')
        self.assertIsNone(config_store.recover(self.path), 'a good file is left alone')

    def test_a_file_from_a_newer_tessera_or_no_backup_changes_nothing(self):
        future = json.dumps(dict(config(), version=config_store.CONFIG_VERSION + 1))
        self.backup(json.dumps(config()))
        self.path.write_text(future, encoding='utf-8')
        self.assertIsNone(config_store.recover(self.path))
        self.assertEqual(self.path.read_text(encoding='utf-8'), future)
        other = Path(self.temp.name) / 'other' / 'profiles.json'
        other.parent.mkdir()
        other.write_text('{broken', encoding='utf-8')
        self.assertIsNone(config_store.recover(other))
        self.assertIsNone(config_store.recover(Path(self.temp.name) / 'missing.json'))

    def test_a_version_1_file_migrates_to_version_2_unchanged_and_validates(self):
        original = json.loads((ROOT / 'tests/fixtures/profiles-v1.json').read_text(encoding='utf-8'))
        self.assertEqual(config_store.version_of(original), 1)
        migrated = config_store.migrate(original)
        self.assertEqual(migrated['version'], 2)
        self.assertEqual({key: value for key, value in migrated.items() if key != 'version'}, original)
        tesserad.validate_config(migrated)


class UpdateNotesTests(unittest.TestCase):
    def test_the_check_returns_the_first_lines_of_the_release_notes(self):
        body = '## Tessera 0.7.0\r\n\r\n' + '\n'.join(f'- change {n}' for n in range(20))
        reply = json.dumps({'tag_name': 'v0.7.0', 'body': body, 'assets': []}).encode()

        class Reply:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, limit):
                return reply[:limit]
        info = updates.check('0.6.3', lambda request, timeout: Reply())
        lines = info['notes'].splitlines()
        self.assertEqual((len(lines), lines[0], lines[-1]), (10, '## Tessera 0.7.0', '- change 8'))
        self.assertEqual(updates.notes_excerpt(None), '')


@unittest.skipIf(importlib.util.find_spec('pystray') is None, 'pystray is not installed')
class TrayRestartTests(unittest.TestCase):
    def make_app(self):
        import tessera_tray
        app = tessera_tray.TrayApp(Mock())
        app.icon = Mock()
        app.host = Mock()  # records each restart instead of starting a thread
        self.enterContext(patch.object(tessera_tray, 'notifications_enabled', return_value=True))  # not the user's own switch
        return app

    def test_a_host_that_died_is_restarted_with_backoff_and_one_notice_per_burst(self):
        app = self.make_app()
        with patch('tessera_tray.firmware_installing', return_value=False):
            app.watch_host(True, 0)
            starts = []
            now = 10.0
            while now < 2000:
                app.watch_host(False, now)
                if app.host.call_count > len(starts):
                    starts.append(now)
                    app.restart_at = None  # what restart_quietly does when the start returns
                now += 1
            waits = [b - a for a, b in zip([10.0, *starts], starts, strict=False)]
            self.assertEqual(waits[:5], [5, 16, 61, 301, 301])
            self.assertEqual(app.icon.notify.call_count, 1)
            app.watch_host(True, 3000)
            app.watch_host(True, 3000 + 600)  # ten minutes up: the next crash starts a new burst
            app.watch_host(False, 4000)
            self.assertEqual(app.icon.notify.call_count, 2)
            self.assertEqual(app.restart_at, 4005)

    def test_no_restart_after_stop_during_a_flash_or_before_the_host_ever_ran(self):
        app = self.make_app()
        with patch('tessera_tray.firmware_installing', return_value=False):
            app.watch_host(False, 0)
            app.watch_host(False, 100)
            app.watch_host(True, 200)
            app.user_stopped = True
            app.watch_host(False, 300)
            app.watch_host(False, 400)
        app.user_stopped = False
        with patch('tessera_tray.firmware_installing', return_value=True):
            app.watch_host(False, 500)
            app.watch_host(False, 600)
        app.host.assert_not_called()
        app.icon.notify.assert_not_called()

    def test_a_failed_automatic_start_is_quiet(self):
        app = self.make_app()
        app.controller.start.side_effect = RuntimeError('port busy')
        app.restart_at = 5
        app.restart_quietly()
        self.assertIsNone(app.restart_at)
        app.icon.notify.assert_not_called()

    def test_the_update_notice_shows_the_version_and_notes(self):
        import tessera_tray
        app = self.make_app()
        app.background = lambda work, *args: work(*args)
        with patch.object(updates, 'check', return_value={'newer': True, 'latest': '0.7.0', 'notes': '- faster'}):
            tessera_tray.TrayApp.check_for_updates(app)
        app.icon.notify.assert_called_once_with('- faster', 'Update available: 0.7.0')


if __name__ == '__main__':
    unittest.main()
