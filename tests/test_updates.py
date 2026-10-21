"""Update check, verified firmware download and the diagnostics bundle; no network."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import diagnostics
import updates
from tessera_app import Editor

FIRMWARE = b'PK-pretend-firmware-zip'
NAME = 'tessera-firmware-0.6.0.zip'


class Reply:
    def __init__(self, body, url='https://github.com/x'):
        self.body, self.url = body if isinstance(body, bytes) else body.encode(), url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.url

    def read(self, limit):
        return self.body[:limit]


def release(tag='v0.6.0', assets=None):
    return {'tag_name': tag, 'html_url': 'https://github.com/catorendal-a11y/tessera-deck/releases/tag/' + tag,
            'assets': assets if assets is not None else [
                {'name': NAME, 'size': len(FIRMWARE), 'browser_download_url': f'https://github.com/r/{NAME}'},
                {'name': 'SHA256SUMS', 'size': 100, 'browser_download_url': 'https://github.com/r/SHA256SUMS'}]}


def router(routes):
    def opener(request, timeout):
        body = routes[request.full_url]
        return body if isinstance(body, Reply) else Reply(body)
    return opener


class VersionTests(unittest.TestCase):
    def test_versions_compare_numerically(self):
        self.assertGreater(updates.parse_version('v0.10.0'), updates.parse_version('0.9.9'))
        self.assertEqual(updates.parse_version('1.2.3'), (1, 2, 3))
        for bad in ('1.2', 'latest', '', 'v1.2.3-beta'):
            with self.assertRaises(ValueError):
                updates.parse_version(bad)


class CheckTests(unittest.TestCase):
    def test_a_newer_release_is_reported_with_its_firmware_and_checksum_files(self):
        info = updates.check('0.5.0', router({updates.RELEASE_API: json.dumps(release())}))
        self.assertTrue(info['newer'])
        self.assertEqual((info['latest'], info['firmware']['name'], info['sums']['name']),
                         ('0.6.0', NAME, 'SHA256SUMS'))

    def test_the_same_or_an_older_release_is_not_newer(self):
        for current in ('0.6.0', '0.7.0'):
            self.assertFalse(updates.check(current, router({updates.RELEASE_API: json.dumps(release())}))['newer'])

    def test_unreadable_answers_are_explained(self):
        for body in ('not json', '[]', '{"tag_name": "nightly"}', '{}'):
            with self.assertRaises(ValueError):
                updates.check('0.5.0', router({updates.RELEASE_API: body}))


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'firmware'
        self.info = updates.check('0.5.0', router({updates.RELEASE_API: json.dumps(release())}))
        self.sums = f'{hashlib.sha256(FIRMWARE).hexdigest()}  {NAME}\n'

    def routes(self, **extra):
        routes = {f'https://github.com/r/{NAME}': FIRMWARE, 'https://github.com/r/SHA256SUMS': self.sums}
        routes.update(extra)
        return router(routes)

    def test_a_matching_checksum_saves_the_package(self):
        target = updates.download_firmware(self.info, self.folder, self.routes())
        self.assertEqual(target.read_bytes(), FIRMWARE)
        self.assertFalse(list(self.folder.glob('*.part')))

    def test_a_mismatch_saves_nothing(self):
        wrong = router({f'https://github.com/r/{NAME}': b'tampered', 'https://github.com/r/SHA256SUMS': self.sums})
        with self.assertRaises(ValueError) as raised:
            updates.download_firmware(self.info, self.folder, wrong)
        self.assertIn('checksum', str(raised.exception))
        self.assertFalse(self.folder.exists() and list(self.folder.iterdir()))

    def test_a_checksum_file_that_does_not_list_the_package_is_refused(self):
        self.sums = f'{"0" * 64}  something-else.zip\n'
        with self.assertRaises(ValueError):
            updates.download_firmware(self.info, self.folder, self.routes())

    def test_only_github_over_https_is_trusted_even_after_redirects(self):
        info = dict(self.info, firmware=dict(self.info['firmware'], url='http://evil.example/' + NAME))
        with self.assertRaises(ValueError):
            updates.download_firmware(info, self.folder, self.routes())
        redirected = self.routes(**{f'https://github.com/r/{NAME}': Reply(FIRMWARE, 'https://evil.example/x.zip')})
        with self.assertRaises(ValueError):
            updates.download_firmware(self.info, self.folder, redirected)
        cdn = self.routes(**{f'https://github.com/r/{NAME}': Reply(FIRMWARE, 'https://objects.githubusercontent.com/x')})
        self.assertTrue(updates.download_firmware(self.info, self.folder, cdn).is_file())

    def test_odd_file_names_and_missing_assets_are_refused(self):
        for firmware in ({'name': '../evil.zip', 'size': 1, 'url': 'https://github.com/x'}, None):
            with self.assertRaises(ValueError):
                updates.download_firmware(dict(self.info, firmware=firmware), self.folder, self.routes())
        with self.assertRaises(ValueError):
            updates.download_firmware(dict(self.info, sums=None), self.folder, self.routes())

    def test_oversized_downloads_are_cut_off(self):
        huge = self.routes(**{f'https://github.com/r/{NAME}': b'x' * (updates.MAX_DOWNLOAD + 5)})
        with self.assertRaises(ValueError):
            updates.download_firmware(self.info, self.folder, huge)


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.config = {'version': 2, 'profiles': {'Main': {'pages': {'First': [
            {'id': 1, 'label': 'SECRET LABEL',
             'actions': [{'type': 'shell', 'command': 'curl -H "Authorization: x" https://private.example'}],
             'hold_actions': [{'type': 'hotkey', 'keys': 'ctrl+c'}]}]}}}, 'triggers': [{}],
            'ambient': {'enabled': True}}

    def test_cleaning_removes_user_names_and_credentials(self):
        text = (r'Opened C:\Users\Jane Doe\Documents\x and C:\Users\jane\AppData; token=abc123 '
                r'password: "hunter2" Authorization: Bearer xyz')
        cleaned = diagnostics.clean(text)
        self.assertNotIn('jane', cleaned.lower().replace('<user>', ''))
        for secret in ('abc123', 'hunter2', 'xyz'):
            self.assertNotIn(secret, cleaned)
        self.assertIn(r'C:\Users\<user>', cleaned)

    def test_the_bundle_has_counts_and_a_cleaned_log_but_never_button_contents(self):
        log = self.folder / 'deck.log'
        log.write_text('\n'.join(f'line {i} C:\\Users\\jane\\x token=abc' for i in range(900)), encoding='utf-8')
        status = {'running': True, 'connection': 'Panel connected',
                  'device': {'connected': True, 'firmware': '0.5.0', 'protocol': 3}}
        target = diagnostics.build(self.folder / 'out', self.config, status, '0.5.0', log)
        with zipfile.ZipFile(target) as archive:
            report = json.loads(archive.read('report.json'))
            log_text = archive.read('host.log').decode()
            everything = archive.read('report.json').decode() + log_text
        self.assertEqual(report['configuration']['buttons'], 1)
        self.assertEqual(report['configuration']['action_types'], {'shell': 1, 'hotkey': 1})
        self.assertEqual(report['host']['device']['firmware'], '0.5.0')
        self.assertEqual(len(log_text.splitlines()), diagnostics.LOG_LINES)
        for private in ('SECRET LABEL', 'private.example', 'Authorization', 'jane', 'abc'):
            self.assertNotIn(private, everything.replace('<user>', ''))

    def test_old_bundles_are_pruned_and_a_missing_log_is_fine(self):
        out = self.folder / 'out'
        out.mkdir()
        for index in range(14):
            (out / f'tessera-diagnostics-2020010{index % 9}-0000{index:02d}.zip').write_bytes(b'x')
        diagnostics.build(out, self.config, {}, '0.5.0', self.folder / 'missing.log')
        self.assertLessEqual(len(list(out.glob('tessera-diagnostics-*.zip'))), 10)


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / 'profiles.json'
        path.write_text(json.dumps({'default_profile': 'Main',
                                    'profiles': {'Main': {'match': [], 'pages': {'First': []}}}}))
        self.editor = Editor(path, dashboard=lambda: {'running': False, 'device': {}})

    def test_downloads_use_the_release_found_by_the_check_never_client_supplied_urls(self):
        with self.assertRaises(ValueError):
            self.editor.command('update-download-firmware', {'url': 'https://evil.example/x.zip'})
        with patch.object(updates, 'check', return_value={'latest': '0.6.0'}) as check:
            self.assertEqual(self.editor.command('update-check', {})['latest'], '0.6.0')
        check.assert_called_once()
        with patch.object(updates, 'download_firmware', return_value=Path('firmware') / NAME) as download:
            result = self.editor.command('update-download-firmware', {'url': 'https://evil.example/x.zip'})
        self.assertEqual(download.call_args.args[0], {'latest': '0.6.0'})
        self.assertIn(NAME, result['message'])

    def test_offline_errors_are_plain(self):
        with patch.object(updates, 'check', side_effect=OSError('down')):
            with self.assertRaises(ValueError) as raised:
                self.editor.command('update-check', {})
        self.assertIn('internet connection', str(raised.exception))

    def test_the_host_log_view_is_cleaned_and_limited(self):
        log = Path(self.temp.name) / 'deck.log'
        lines = [f'line {i} C:\\Users\\jane\\x token=abc' for i in range(300)]
        log.write_text('\n'.join(lines), encoding='utf-8')
        with patch.object(diagnostics, 'log_tail', wraps=diagnostics.log_tail) as tail:
            text = diagnostics.log_tail(log, 50)
        self.assertEqual(len(text.splitlines()), 50)
        self.assertNotIn('jane', text.replace('<user>', ''))
        self.assertNotIn('abc', text)
        self.assertEqual(len(diagnostics.log_tail(log, 10 ** 6).splitlines()), 300, 'a huge request is capped, never more than the log has')
        self.assertEqual(diagnostics.log_tail(Path(self.temp.name) / 'missing.log'), '(no log found)')
        tail.assert_called_once()

    def test_the_host_log_command_answers_even_without_a_log(self):
        with patch.object(diagnostics, 'log_tail', return_value='hello') as tail:
            self.assertEqual(self.editor.command('host-log', {'lines': 20}), {'log': 'hello'})
            self.assertEqual(self.editor.command('host-log', {'lines': 'many'}), {'log': 'hello'})
        self.assertEqual([call.args[1] for call in tail.call_args_list], [20, 200])

    def test_the_diagnostics_command_returns_the_bundle_path(self):
        with patch.object(diagnostics, 'build', return_value=Path('diagnostics/tessera-diagnostics-x.zip')) as build, \
                patch('os.startfile', create=True):
            result = self.editor.command('diagnostics', {})
        build.assert_called_once()
        self.assertIn('no button contents', result['message'])


if __name__ == '__main__':
    unittest.main()
