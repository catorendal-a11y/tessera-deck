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

    def test_shell_mode_refuses_powershell_metacharacters_and_keeps_plain_text(self):
        for bad in ("'+(Start-Process calc)+'", '{x}', '@(1)', 'a+b', '’x'):
            with self.assertRaises(ValueError, msg=bad):
                substitute("powershell -c \"Write-Output '$(v)'\"", {'v': bad}, 'shell')
        self.assertEqual(substitute('echo "$(v)"', {'v': 'Blåbær - Live 2.0, 12:30/x_y'}, 'shell'),
                         'echo "Blåbær - Live 2.0, 12:30/x_y"')

    def test_shell_mode_keeps_a_value_one_argument(self):
        self.assertEqual(substitute('notepad $(v)', {'v': 'x.txt /p'}, 'shell'), 'notepad "x.txt /p"')
        self.assertEqual(substitute('tool --name=$(v) go', {'v': 'a --config evil.ini'}, 'shell'),
                         'tool --name="a --config evil.ini" go')
        self.assertEqual(substitute('notify.exe "$(v)"', {'v': 'a /p'}, 'shell'), 'notify.exe "a /p"',
                         'a value the user already quoted is not quoted twice')
        self.assertEqual(substitute('tool $(v)', {'v': 'plain'}, 'shell'), 'tool plain')

    def test_shell_mode_refuses_a_value_that_starts_like_an_option(self):
        for template in ('tool $(v)', 'tool "$(v)"', '$(v)'):
            for bad in ('/p', '--config=evil.ini', '-x', '-5 /p'):
                with self.assertRaises(ValueError, msg=(template, bad)):
                    substitute(template, {'v': bad}, 'shell')
        self.assertEqual(substitute('volume $(v)', {'v': '-5'}, 'shell'), 'volume -5')
        self.assertEqual(substitute('tool --level=$(v) C:/x/$(v)', {'v': '-x'}, 'shell'), 'tool --level=-x C:/x/-x')
        self.assertEqual(substitute('echo "Track: $(v)"', {'v': '-x'}, 'shell'), 'echo "Track: -x"')
        self.assertEqual(substitute('notify.exe "Now playing: $(v)"', {'v': '/Rock'}, 'shell'),
                         'notify.exe "Now playing: /Rock"', 'inside quotes it is plain text')

    def test_url_mode_percent_encodes(self):
        self.assertEqual(substitute('/q?x=$(v)', {'v': 'a b&c'}, 'url'), '/q?x=a%20b%26c')


if __name__ == '__main__':
    unittest.main()
