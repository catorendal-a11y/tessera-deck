"""HTTP actions only talk http(s): checked when the profile is saved and again after variables are filled in."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck
import host_support  # noqa: E402
from substitution import check_web_url


def config_with(url):
    config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
    config['profiles']['main']['pages']['main'][0]['actions'] = [{'type': 'http', 'url': url}]
    return config


class WebUrlTests(unittest.TestCase):
    def test_only_http_and_https_with_a_host_pass(self):
        self.assertEqual(check_web_url('https://example.com/a?b=1'), 'https://example.com/a?b=1')
        self.assertEqual(check_web_url('http://127.0.0.1:8080/x'), 'http://127.0.0.1:8080/x')
        for bad in ('ftp://example.com', 'file:///C:/Windows/win.ini', 'x', 'https://', '//example.com', ''):
            with self.subTest(bad), self.assertRaises(ValueError):
                check_web_url(bad)


class SavedProfileTests(unittest.TestCase):
    def test_a_profile_with_a_non_web_address_is_refused(self):
        for bad in ('ftp://example.com', 'file:///C:/Windows/win.ini', 'example.com/x'):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, 'http'):
                deck.validate_config(config_with(bad))

    def test_web_addresses_and_addresses_that_start_with_a_variable_are_accepted(self):
        for good in ('https://example.com/hook', 'http://127.0.0.1:9/x', '$(var:base)/hook'):
            with self.subTest(good):
                deck.validate_config(config_with(good))


class RunTimeTests(unittest.TestCase):
    def make_daemon(self):
        daemon = host_support.test_daemon(port='TEST', no_focus=True)
        daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
        daemon.stop.clear()
        return daemon

    def test_a_variable_cannot_turn_the_request_into_a_file_or_ftp_address(self):
        daemon = self.make_daemon()
        daemon.custom_vars['base'] = 'file:///C:/Windows/win.ini'
        with patch.object(deck.WEB_OPENER, 'open', Mock()) as urlopen:
            with self.assertRaisesRegex(ValueError, 'http'):
                daemon.run_action({'type': 'http', 'url': '$(var:base)'})
        urlopen.assert_not_called()

    def test_the_address_can_come_from_the_environment(self):
        daemon = self.make_daemon()
        environment = {'TESSERA_TEST_HOOK': 'https://example.com/secret-hook'}
        with patch.dict(deck.os.environ, environment), patch.object(deck.WEB_OPENER, 'open', MagicMock()) as urlopen:
            daemon.run_action({'type': 'http', 'url': '$(env:TESSERA_TEST_HOOK)'})
        self.assertEqual(urlopen.call_args.args[0].full_url, 'https://example.com/secret-hook')


class RedirectTests(unittest.TestCase):
    def redirect(self, old, new):
        request = deck.urllib.request.Request(old, headers={'Authorization': 'Bearer x'})
        return deck.SafeRedirects().redirect_request(request, None, 302, 'Found', {}, new)

    def test_a_redirect_down_to_http_or_to_another_scheme_is_refused(self):
        with self.assertRaises(deck.CommandFailed):
            self.redirect('https://api.example.com/a', 'http://api.example.com/a')
        with self.assertRaises(deck.CommandFailed):
            self.redirect('http://api.example.com/a', 'ftp://api.example.com/a')

    def test_a_redirect_to_another_host_goes_without_the_headers(self):
        moved = self.redirect('https://example.com/a', 'https://www.example.com/a')
        self.assertEqual((moved.full_url, moved.headers), ('https://www.example.com/a', {}))

    def test_a_redirect_on_the_same_host_keeps_the_headers(self):
        moved = self.redirect('http://api.example.com/a', 'https://api.example.com/b')
        self.assertEqual((moved.full_url, moved.get_header('Authorization')), ('https://api.example.com/b', 'Bearer x'))


if __name__ == '__main__':
    unittest.main()
