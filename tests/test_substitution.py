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


if __name__ == '__main__':
    unittest.main()
