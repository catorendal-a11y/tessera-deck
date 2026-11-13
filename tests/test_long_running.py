"""A host that runs for weeks: the log stays small and unchanged plugin folders are not read again every 3 s."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import plugins  # noqa: E402
import tesserad  # noqa: E402


class LogRotationTests(unittest.TestCase):
    def test_a_full_log_moves_to_dot_one_and_writing_starts_again(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'deck.local.log'
            with path.open('w', encoding='utf-8') as log:
                log.write('x' * 50)
                log.flush()
                with patch.object(tesserad, 'LOG_PATH', path), patch.object(tesserad, 'LOG_KEEP_BYTES', 10), \
                        patch.object(tesserad.sys, 'stdout', log):
                    tesserad.rotate_log()
                    log.write('new')
                    log.flush()
            self.assertEqual(path.with_name('deck.local.log.1').read_text(encoding='utf-8'), 'x' * 50)
            self.assertEqual(path.read_text(encoding='utf-8'), 'new')


class PluginFolderTests(unittest.TestCase):
    def test_manifests_are_read_again_only_after_a_folder_changed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'demo').mkdir()
            (root / 'demo' / 'plugin.json').write_text('{}', encoding='utf-8')
            manager = plugins.PluginManager(root, root / 'logs', lambda: '', lambda *_: '', lambda _: None)
            with patch.object(plugins, 'discover', return_value=([], [])) as discover:
                manager.refresh()
                manager.refresh()
                self.assertEqual(discover.call_count, 1)
                (root / 'other').mkdir()
                (root / 'other' / 'plugin.json').write_text('{}', encoding='utf-8')
                manager.refresh()
            self.assertEqual(discover.call_count, 2)


if __name__ == '__main__':
    unittest.main()
