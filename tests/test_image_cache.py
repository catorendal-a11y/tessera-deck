"""Images the panel has dropped from its 8 MiB cache are sent again when a page needs them."""
from collections import OrderedDict
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import deck_assets  # noqa: E402
import panel_serial  # noqa: E402


def image(frames, size=15):
    """An ADI1 header of 72 x 72 x 4 bytes per frame on the panel, padded to `size` bytes."""
    return (b'ADI1' + bytes((72, 72, frames))).ljust(size, b'\0')


class Waits(threading.Event):
    """asset_done, which also notes in the panel's wire log each time the host waits for an answer."""

    def __init__(self, wire):
        super().__init__()
        self.wire = wire

    def wait(self, timeout=None):
        self.wire.append('wait')
        return super().wait(timeout)


def firmware_ack(received, size):
    """What esp/main/deck_images.cpp answers after an AD_IMG_DATA line of an upload begun with "ack"."""
    return f'AD_IMG_DATA OK {received}' if received % 2048 == 0 or received == size else None


class ImageCacheTests(unittest.TestCase):
    def panel(self, info=None, data_answer=firmware_ack):
        """A panel that answers as the firmware does, through asset_reply and asset_done as the reader loop would."""
        panel = panel_serial.PanelSerial.__new__(panel_serial.PanelSerial)
        panel.write_lock, panel.assets_sent, panel.info = threading.RLock(), OrderedDict(), info or {}
        panel.ser, panel.uploads, panel.wire = Mock(), [], []
        panel.asset_done = Waits(panel.wire)
        upload = {}

        def answer(line):
            panel.asset_reply = line
            panel.asset_done.set()

        def send_line(line):
            panel.wire.append(line)
            words = line.split()
            if words[0] == 'AD_IMG_BEGIN':
                panel.uploads.append(words[1])
                upload.update(size=int(words[2]), received=0, ack=words[-1] == 'ack')
            elif words[0] == 'AD_IMG_DATA' and upload['ack']:
                upload['received'] += len(words[2]) // 2
                if reply := data_answer(upload['received'], upload['size']):
                    answer(reply)
            elif line == 'AD_IMG_END':
                answer('AD_IMG_END OK ' + panel.uploads[-1])
        panel.send_line = send_line
        return panel

    def push(self, panel, raw):
        sleep = Mock(side_effect=lambda seconds: panel.wire.append(('sleep', seconds)))
        with patch.object(panel_serial.time, 'sleep', sleep):
            panel.push_assets([{'icon': 'im:a'}], Mock(read=lambda name: raw))
        return sleep

    def test_old_firmware_gets_160_byte_lines_and_a_pause_after_every_four(self):
        panel, raw = self.panel(), image(12, 1300)
        self.push(panel, raw)
        data = [f'AD_IMG_DATA {offset} ' + raw[offset:offset + 160].hex() for offset in range(0, 1300, 160)]
        self.assertEqual(panel.wire, [f'AD_IMG_BEGIN im:a 1300 {zlib.crc32(raw)}', *data[:4], ('sleep', .01),
                                      *data[4:8], ('sleep', .01), data[8], 'AD_IMG_END', 'wait'])
        self.assertEqual(panel.ser.flush.call_count, 2)
        self.assertEqual(panel.assets_sent, {'im:a': 72 * 72 * 4 * 12})

    def test_a_panel_with_img_ack_gets_512_byte_lines_and_is_waited_for_every_2048_bytes(self):
        panel, raw = self.panel({'imgAck': 1}), image(12, 5000)
        sleep = self.push(panel, raw)
        data = [f'AD_IMG_DATA {offset} ' + raw[offset:offset + 512].hex() for offset in range(0, 5000, 512)]
        self.assertEqual(panel.wire, [f'AD_IMG_BEGIN im:a 5000 {zlib.crc32(raw)} ack', *data[:4], 'wait',
                                      *data[4:8], 'wait', *data[8:], 'wait', 'AD_IMG_END', 'wait'])
        self.assertEqual(len(data[0]), len('AD_IMG_DATA 0 ') + 1024)
        sleep.assert_not_called()
        panel.ser.flush.assert_not_called()
        self.assertEqual(panel.assets_sent, {'im:a': 72 * 72 * 4 * 12})

    def test_a_refused_image_line_stops_the_upload_at_the_window(self):
        panel = self.panel({'imgAck': 1}, data_answer=lambda received, size: 'AD_IMG_DATA INVALID')
        with self.assertRaisesRegex(ValueError, '^AD_IMG_DATA INVALID$'):
            self.push(panel, image(12, 5000))
        self.assertEqual(panel.wire[-1], 'wait')
        self.assertEqual(len(panel.wire), 6, 'BEGIN, the first window of 4 lines and the wait; no AD_IMG_END')
        self.assertEqual(panel.assets_sent, {})

    def test_a_missing_image_acknowledgement_times_out(self):
        panel = self.panel({'imgAck': 1}, data_answer=lambda received, size: None)
        panel.image_seconds = 0.01
        with self.assertRaisesRegex(TimeoutError, 'did not acknowledge the image data'):
            self.push(panel, image(12, 5000))
        self.assertEqual(panel.assets_sent, {})

    def test_an_answer_for_other_bytes_is_refused(self):
        panel = self.panel({'imgAck': 1}, data_answer=lambda received, size: 'AD_IMG_DATA OK 1')
        with self.assertRaisesRegex(ValueError, '^AD_IMG_DATA OK 1$'):
            self.push(panel, image(12, 5000))

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

    def test_the_reader_hands_an_image_data_answer_to_the_upload(self):
        import host_support
        daemon = host_support.test_daemon()
        daemon.log, daemon.publish_runtime = Mock(), Mock()
        panel = daemon.panel = Mock()
        panel.read_lines.side_effect = [['AD_IMG_DATA OK 2048'], OSError('unplugged')]
        daemon.reader_loop(panel)
        self.assertEqual(panel.asset_reply, 'AD_IMG_DATA OK 2048')
        panel.asset_done.set.assert_called_once_with()

if __name__ == '__main__':
    unittest.main()


class AssetsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.assets = deck_assets.Assets(Path(self.folder.name) / 'profiles.json')

    def test_export_skips_an_image_that_has_no_file(self):
        self.assets.root.mkdir()
        (self.assets.root / 'aaaaaaaaaaaa.png').write_bytes(b'png')
        config = {'pages': [{'buttons': [{'icon': 'im:aaaaaaaaaaaa'}, {'icon': 'im:bbbbbbbbbbbb'}]}]}
        self.assertEqual(list(self.assets.export(config)), ['im:aaaaaaaaaaaa'])

    def test_a_failed_program_icon_lookup_is_tried_again_after_a_while(self):
        button = {'icon': 'app', 'actions': [{'type': 'open', 'target': r'E:\laterpp.exe'}]}
        results = iter([None, 'im:cccccccccccc', 'im:dddddddddddd'])
        with patch.object(self.assets, 'rebuild_from_actions', lambda _: next(results)),                 patch.object(deck_assets.time, 'monotonic', side_effect=[0, 1, 100, 101]):
            self.assertEqual(self.assets.icon_for(button), 'ok')
            self.assertEqual(self.assets.icon_for(button), 'ok')  # inside the retry window
            self.assertEqual(self.assets.icon_for(button), 'im:cccccccccccc')
            self.assertEqual(self.assets.icon_for(button), 'im:cccccccccccc')  # a found icon stays cached
