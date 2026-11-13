"""Images the panel has dropped from its 8 MiB cache are sent again when a page needs them."""
from collections import OrderedDict
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import panel_serial  # noqa: E402


def image(frames):
    return b'ADI1' + bytes((72, 72, frames)) + b'\0' * 8  # 72 x 72 x 4 bytes per frame on the panel


class ImageCacheTests(unittest.TestCase):
    def panel(self):
        panel = panel_serial.PanelSerial.__new__(panel_serial.PanelSerial)
        panel.write_lock, panel.asset_done, panel.assets_sent = threading.RLock(), threading.Event(), OrderedDict()
        panel.ser = Mock()
        panel.uploads = []

        def send_line(line):
            if line.startswith('AD_IMG_BEGIN'):
                panel.uploads.append(line.split()[1])
            if line == 'AD_IMG_END':
                panel.asset_reply = 'AD_IMG_END OK ' + panel.uploads[-1]
                panel.asset_done.set()
        panel.send_line = send_line
        return panel

    def test_an_image_the_panel_dropped_is_uploaded_again(self):
        panel, assets = self.panel(), Mock(read=lambda name: image(12))
        keys = lambda *names: [{'icon': name} for name in names]  # noqa: E731
        with patch.object(panel_serial, 'PANEL_CACHE_BYTES', 2 * 72 * 72 * 4 * 12), patch.object(panel_serial.time, 'sleep'):
            panel.push_assets(keys('im:a', 'im:b'), assets)
            panel.push_assets(keys('im:a', 'im:b'), assets)
            self.assertEqual(panel.uploads, ['im:a', 'im:b'], 'what the panel still has is not sent twice')
            panel.push_assets(keys('im:c'), assets)  # the panel now drops the oldest image no key shows
            panel.push_assets(keys('im:a'), assets)
        self.assertEqual(panel.uploads, ['im:a', 'im:b', 'im:c', 'im:a'])


class PanelAsksTests(unittest.TestCase):
    def test_an_image_the_panel_asks_for_is_sent_again_once_a_minute(self):
        import host_support
        daemon = host_support.test_daemon()
        daemon.panel, daemon.log, daemon.publish_runtime = Mock(), Mock(), Mock()
        daemon.panel.assets_sent = OrderedDict({'im:a': 1})
        with patch.object(daemon, 'push_page') as push:
            daemon.handle_job(('image-missing', 'im:a'))
            daemon.handle_job(('image-missing', 'im:a'))
        self.assertNotIn('im:a', daemon.panel.assets_sent)
        push.assert_called_once_with(force=True)

if __name__ == '__main__':
    unittest.main()
