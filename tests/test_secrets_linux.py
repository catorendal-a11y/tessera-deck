"""Plugin secrets in the system keyring (Linux). A fake keyring stands in: the tests never touch the real one."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_marks import linux_only_module
linux_only_module(__name__)
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import secrets_store
from platform_linux import secrets as keyring_secrets


class FakeKeyring(types.SimpleNamespace):
    def __init__(self):
        super().__init__(items={})

    def set_password(self, service, name, value):
        self.items[(service, name)] = value

    def get_password(self, service, name):
        return self.items.get((service, name))

    def delete_password(self, service, name):
        del self.items[(service, name)]


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux only')
class KeyringSecretsTests(unittest.TestCase):
    def setUp(self):
        self.keyring = FakeKeyring()
        patcher = patch.object(keyring_secrets, '_keyring', return_value=self.keyring)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def config(**settings):
        return {'plugins': {'demo': {'enabled': True, 'settings': dict(settings, host='nas.local')}}}

    def test_a_secret_goes_to_the_keyring_and_the_profile_keeps_only_a_reference(self):
        sealed = secrets_store.seal_plugins(self.config(password='hunter2', api_key='k-1'))
        settings = sealed['plugins']['demo']['settings']
        self.assertTrue(settings['password'].startswith('$(keyring:') and secrets_store.is_sealed(settings['api_key']))
        self.assertEqual(settings['host'], 'nas.local')
        self.assertNotIn('hunter2', json.dumps(sealed))
        self.assertNotIn('k-1', json.dumps(sealed))
        self.assertEqual(sorted(self.keyring.items.values()), ['hunter2', 'k-1'])
        self.assertEqual(secrets_store.open_settings(settings)['password'], 'hunter2')

    def test_an_unchanged_secret_keeps_its_reference_and_a_changed_one_gets_a_new_value(self):
        first = secrets_store.seal_plugins(self.config(token='abc'))
        again = secrets_store.seal_plugins(self.config(token='abc'), first)
        self.assertEqual(first, again)
        self.assertEqual(len(self.keyring.items), 1)
        changed = secrets_store.seal_plugins(self.config(token='new'), first)
        self.assertNotEqual(first, changed)
        self.assertEqual(secrets_store.unprotect(changed['plugins']['demo']['settings']['token']), 'new')

    def test_a_secret_the_keyring_no_longer_has_opens_as_empty_so_the_plugin_asks_again(self):
        self.assertEqual(secrets_store.unprotect('$(keyring:gone)'), '')

    def test_empty_values_and_values_that_are_not_secrets_never_reach_the_keyring(self):
        sealed = secrets_store.seal_plugins(self.config(password=''))
        self.assertEqual(sealed['plugins']['demo']['settings']['password'], '')
        self.assertEqual(self.keyring.items, {})

    def test_a_missing_keyring_refuses_to_save_instead_of_writing_plain_text(self):
        with patch.object(keyring_secrets, '_keyring', side_effect=OSError('No system keyring was found')):
            with self.assertRaisesRegex(OSError, 'No system keyring'):
                secrets_store.seal_plugins(self.config(password='hunter2'))
            self.assertEqual(secrets_store.unprotect('$(keyring:abc)'), '')  # opening never raises

    def test_a_keyring_that_fails_to_store_is_reported(self):
        self.keyring.set_password = lambda *args: (_ for _ in ()).throw(RuntimeError('locked'))
        with self.assertRaisesRegex(OSError, 'refused the secret: locked'):
            keyring_secrets.store('x')


if __name__ == '__main__':
    unittest.main()
