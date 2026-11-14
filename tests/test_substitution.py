import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))

from substitution import substitute  # noqa: E402


class SubstituteTests(unittest.TestCase):
    def test_replaces_known_tokens_and_blanks_unset_custom_variables(self):
        self.assertEqual(substitute('a $(x) b $(var:nope) $(other)', {'x': '1'}), 'a 1 b  $(other)')

    def test_a_value_is_never_expanded_again(self):
        variables = {'a': '$(b)', 'b': 'secret'}
        self.assertEqual(substitute('$(a)', variables), '$(b)')
        self.assertEqual(substitute('$(b) $(a)', variables), 'secret $(b)')

    def test_shell_mode_refuses_unsafe_values_only_for_tokens_in_use(self):
        variables = {'bad': 'x & y', 'ok': 'fine'}
        self.assertEqual(substitute('echo $(ok)', variables, 'shell'), 'echo fine')
        with self.assertRaises(ValueError):
            substitute('echo $(bad)', variables, 'shell')

    def test_url_mode_percent_encodes(self):
        self.assertEqual(substitute('/q?x=$(v)', {'v': 'a b&c'}, 'url'), '/q?x=a%20b%26c')

    def test_environment_references_come_from_the_template_only(self):
        env = {'SECRET': 'hunter2'}
        self.assertEqual(substitute('Bearer $(env:SECRET)', {}, None, env), 'Bearer hunter2')
        self.assertEqual(substitute('$(env:NOPE)|', {}, None, env), '|')
        self.assertEqual(substitute('x $(v)', {'v': '$(env:SECRET)'}, None, env), 'x $(env:SECRET)')
        self.assertEqual(substitute('$(env:SECRET)', {}, 'url', {'SECRET': 'https://h/a b'}), 'https://h/a b')


class RedirectTests(unittest.TestCase):
    def follow(self, old, new):
        import urllib.request
        from substitution import _SameHostRedirects
        return _SameHostRedirects().redirect_request(urllib.request.Request(old, headers={'Authorization': 'x'}),
                                                     None, 302, 'Found', {}, new)

    def test_same_host_redirect_is_followed(self):
        self.assertIsNotNone(self.follow('https://a.example/x', 'https://a.example/y'))

    def test_other_host_downgrade_and_odd_schemes_are_refused(self):
        import urllib.error
        for new in ('https://evil.example/', 'http://a.example/', 'ftp://a.example/'):
            with self.assertRaises(urllib.error.HTTPError):
                self.follow('https://a.example/x', new)


if __name__ == '__main__':
    unittest.main()
