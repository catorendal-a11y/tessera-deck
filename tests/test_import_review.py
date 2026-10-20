"""Import review, secret redaction and safe variable substitution in shell and HTTP actions."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck
from import_review import redact_secrets, review, strip_executable
from tessera_app import Editor


def bundle():
    return {'default_profile': 'Main', 'profiles': {'Main': {'match': [], 'pages': {'First': [
        {'id': 1, 'label': 'Safe', 'actions': [{'type': 'hotkey', 'keys': 'ctrl+c'}]},
        {'id': 2, 'label': 'Run', 'actions': [{'type': 'shell', 'command': 'del /q C:\\temp\\*'}]},
        {'id': 3, 'label': 'Web', 'actions': [{'type': 'http', 'url': 'https://example.com/hook', 'method': 'POST',
                                               'body': 'x', 'headers': {'Authorization': 'Bearer secret123',
                                                                      'Content-Type': 'application/json'}}]},
        {'id': 4, 'label': 'Docs', 'actions': [{'type': 'open', 'target': 'https://example.com'}],
         'hold_actions': [{'type': 'open', 'target': 'C:\\Tools\\thing.exe'}]},
        {'id': 5, 'label': 'Toggle', 'actions': [], 'states': [
            {'label': 'A', 'actions': [{'type': 'shell', 'command': 'echo a'}]},
            {'label': 'B', 'actions': [{'type': 'hotkey', 'keys': 'ctrl+v'}]}]}]}}},
        'triggers': [{'when': {'type': 'startup'}, 'actions': [{'type': 'shell', 'command': 'calc'}]}]}


class ReviewTests(unittest.TestCase):
    def test_everything_that_executes_code_or_reaches_the_network_is_listed_with_its_location(self):
        findings = review(bundle())
        by_where = {(f['where'], f['kind']): f for f in findings}
        self.assertEqual(by_where[("Profile 'Main' / page 'First' / button 2 'Run'", 'shell')]['risk'], 'high')
        self.assertEqual(by_where[("Profile 'Main' / page 'First' / button 3 'Web'", 'http')]['risk'], 'medium')
        locations = {f['where'] for f in findings}
        self.assertIn("Profile 'Main' / page 'First' / button 4 'Docs' (long press)", locations)
        self.assertIn("Profile 'Main' / page 'First' / button 5 'Toggle' state 1", locations)
        automatic = [f for f in findings if f['automatic']]
        self.assertEqual([(f['kind'], f['risk']) for f in automatic], [('shell', 'high')])
        self.assertFalse(any("button 1 'Safe'" in where for where in locations))
        self.assertFalse(any('https://example.com' in f['detail'] for f in findings if f['kind'] == 'open'))

    def test_the_bundled_default_profiles_have_no_web_calls_no_automatic_rules_and_only_launch_commands(self):
        config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        findings = review(config)
        self.assertFalse([f for f in findings if f['kind'] == 'http' or f['automatic']])
        self.assertTrue(all(f['detail'].startswith('runs the command: start ""')
                            for f in findings if f['kind'] == 'shell'))

    def test_strip_executable_removes_commands_requests_launches_and_automatic_rules(self):
        safe = strip_executable(bundle())
        self.assertEqual(review(safe), [])
        self.assertEqual(safe['triggers'], [])
        page = safe['profiles']['Main']['pages']['First']
        self.assertEqual(page[0]['actions'], [{'type': 'hotkey', 'keys': 'ctrl+c'}])
        self.assertEqual(page[3]['actions'], [{'type': 'open', 'target': 'https://example.com'}])
        deck.validate_config(safe)

    def test_original_bundle_is_not_modified_by_review_strip_or_redaction(self):
        original = bundle()
        snapshot = copy.deepcopy(original)
        review(original)
        strip_executable(original)
        redact_secrets(original)
        self.assertEqual(original, snapshot)

    def test_export_replaces_credentials_with_environment_references(self):
        shared, names = redact_secrets(bundle())
        headers = shared['profiles']['Main']['pages']['First'][2]['actions'][0]['headers']
        self.assertEqual(headers['Authorization'], '$(env:TESSERA_AUTHORIZATION)')
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(names, ['TESSERA_AUTHORIZATION'])
        self.assertNotIn('secret123', json.dumps(shared))


class EditorCommandTests(unittest.TestCase):
    def test_editor_reviews_and_sanitizes_a_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'profiles.json'
            path.write_text(json.dumps(bundle()))
            editor = Editor(path, dashboard=lambda: {'running': False, 'device': {}})
            findings = editor.command('review', {'config': bundle()})['findings']
            self.assertGreaterEqual(len(findings), 5)
            safe = editor.command('sanitize', {'config': bundle()})['config']
            self.assertEqual(review(safe), [])
            with self.assertRaises(ValueError):
                editor.command('review', {'config': {'profiles': {}}})


class SubstitutionTests(unittest.TestCase):
    def daemon(self):
        daemon = deck.Daemon(types.SimpleNamespace(profiles=str(ROOT / 'host/profiles.default.json'), port='TEST',
                                                   verbose=False, no_focus=True, deck_only=True))
        daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
        return daemon

    def test_shell_commands_refuse_values_that_could_change_the_command(self):
        daemon = self.daemon()
        daemon.custom_vars['name'] = 'build & del *'
        with self.assertRaises(ValueError):
            daemon.substitute('echo $(var:name)', 'shell')
        daemon.custom_vars['name'] = 'release-1.2'
        self.assertEqual(daemon.substitute('echo $(var:name)', 'shell'), 'echo release-1.2')
        daemon.custom_vars['bad'] = 'a"b'
        with self.assertRaises(ValueError):
            daemon.run_action({'type': 'shell', 'command': 'echo $(var:bad)'})

    def test_urls_percent_encode_variable_values_but_text_labels_stay_plain(self):
        daemon = self.daemon()
        daemon.custom_vars['q'] = 'a b&c=d/é'
        self.assertEqual(daemon.substitute('https://x.test/?q=$(var:q)', 'url'),
                         'https://x.test/?q=a%20b%26c%3Dd%2F%C3%A9')
        self.assertEqual(daemon.substitute('Hello $(var:q)'), 'Hello a b&c=d/é')

    def test_http_headers_and_body_expand_environment_credentials_at_run_time(self):
        daemon = self.daemon()
        seen = {}

        def fake_urlopen(request, timeout):
            seen['headers'] = dict(request.header_items())
            seen['body'] = request.data
            response = Mock()
            response.__enter__ = Mock(return_value=Mock(read=Mock(return_value=b'')))
            response.__exit__ = Mock(return_value=False)
            return response

        with patch.dict(os.environ, {'TESSERA_TOKEN': 'tok-1'}), \
                patch.object(deck.urllib.request, 'urlopen', fake_urlopen):
            daemon.run_action({'type': 'http', 'url': 'http://127.0.0.1/x', 'method': 'POST',
                               'headers': {'Authorization': 'Bearer $(env:TESSERA_TOKEN)'},
                               'body': '{"k":"$(env:TESSERA_TOKEN)","missing":"$(env:NOPE_NOT_SET)"}'})
        self.assertEqual(seen['headers']['Authorization'], 'Bearer tok-1')
        self.assertEqual(seen['body'], b'{"k":"tok-1","missing":""}')


if __name__ == '__main__':
    unittest.main()
