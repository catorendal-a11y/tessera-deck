"""Firmware limits that keep a port writer from crashing the panel or wearing out its flash."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def config_value(path, name):
    match = re.search(rf'^{name}=(\d+)$', (ROOT / path).read_text(encoding='utf-8'), re.M)
    return int(match.group(1)) if match else None


class FirmwareHardeningTests(unittest.TestCase):
    def test_cjson_nesting_is_shallow_in_both_configs(self):
        # cJSON recurses per level; 1000 levels overflow the 24 KB console and 10 KB main task stacks.
        for path in ('sdkconfig.defaults', 'sdkconfig'):
            limit = config_value(path, 'CONFIG_CJSON_NESTING_LIMIT')
            self.assertIsNotNone(limit, path)
            self.assertLessEqual(limit, 32, path)
            self.assertGreaterEqual(limit, 8, path)  # the protocol itself nests about 6 levels

    def test_brightness_reaches_nvs_only_through_the_rate_limit(self):
        firmware = (ROOT / 'main/main.cpp').read_text(encoding='utf-8')
        self.assertIn('BRIGHTNESS_SAVE_INTERVAL_US = 60LL * 1000000', firmware)
        calls = re.findall(r'\bsave_brightness\(', firmware)
        # the definition plus the single call in brightness_flush_if_due
        self.assertEqual(len(calls), 2)
        flush = firmware[firmware.index('static void brightness_flush_if_due'):]
        flush = flush[:flush.index('\n}\n')]
        self.assertIn('save_brightness(', flush)
        self.assertIn('BRIGHTNESS_SAVE_INTERVAL_US', flush)


if __name__ == '__main__':
    unittest.main()
