"""The editor is told when the layout is too big for the panel to keep in flash for offline use."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck


class LayoutSizeTests(unittest.TestCase):
    def test_the_size_is_what_the_panel_receives(self):
        buttons = [{'id': 1, 'label': 'Æøå', 'icon': 'ok'}]
        sent = []
        panel = deck.PanelSerial.__new__(deck.PanelSerial)
        panel.push_payload = sent.append
        panel.push_buttons(buttons)
        self.assertEqual(deck.layout_bytes(buttons), len(sent[0].encode()))

    def test_the_offline_limit_matches_the_firmware(self):
        firmware = (ROOT / 'main/main.cpp').read_text(encoding='utf-8')
        self.assertIn(f'LAYOUT_MAX = {deck.OFFLINE_LAYOUT_BYTES};', firmware)

    def test_the_runtime_state_carries_the_size_and_the_controller_passes_it_on(self):
        daemon = deck.Daemon(types.SimpleNamespace(profiles=str(ROOT / 'host/profiles.default.json'), port='TEST',
                                                   verbose=False, no_focus=True, deck_only=True))
        daemon.log, daemon.panel = Mock(), Mock()
        with tempfile.TemporaryDirectory() as folder:
            daemon.runtime_path = Path(folder) / 'runtime.json'
            daemon.publish_runtime(True, force=True)
            published = json.loads(daemon.runtime_path.read_text(encoding='utf-8'))
        self.assertEqual(published['layout_bytes'], deck.layout_bytes(daemon.current_buttons()))
        import deck_control
        self.assertIn('layout_bytes', Path(deck_control.__file__).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
