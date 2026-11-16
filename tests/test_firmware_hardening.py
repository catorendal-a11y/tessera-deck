"""Firmware limits that keep a port writer from crashing the panel or wearing out its flash."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def config_value(path, name):
    match = re.search(rf'^{name}=(\d+)$', (ROOT / path).read_text(encoding='utf-8'), re.M)
    return int(match.group(1)) if match else None


def c_function(path, signature):
    source = (ROOT / path).read_text(encoding='utf-8')
    body = source[source.index(signature):]
    return body[:body.index('\n}\n')]


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

    def test_api_key_command_survives_nvs_that_never_started(self):
        # main.cpp skips api_server_init when NVS fails, so the key mutex is NULL and taking it would assert.
        load_key = c_function('main/api/api_server.c', 'static esp_err_t load_key(')
        guard = load_key.find('if (!s_key_mutex) return')
        self.assertNotEqual(guard, -1)
        self.assertLess(guard, load_key.index('xSemaphoreTake(s_key_mutex'))

    def test_one_lan_host_cannot_hold_every_api_slot(self):
        server = (ROOT / 'main/api/api_server.c').read_text(encoding='utf-8')
        slots = int(re.search(r'^#define SLOTS (\d+)', server, re.M).group(1))
        per_host = re.search(r'^#define PENDING_PER_HOST (\d+)', server, re.M)
        self.assertIsNotNone(per_host)
        self.assertLess(int(per_host.group(1)), slots)  # the rest stay free for Home Assistant's host
        pick = c_function('main/api/api_server.c', 'static slot_t *pick_slot(')
        self.assertIn('same_ip_pending < PENDING_PER_HOST) return free_slot', pick)
        self.assertNotIn('if (slot->fd < 0) return slot;', pick)

    def test_late_c6_answer_clears_no_coprocessor(self):
        # The init timer reports no_coprocessor after 15 s; a C6 that answers later is shown as connecting.
        bring_up = c_function('main/wifi_service.c', 'static bool bring_up(')
        ready = bring_up[bring_up.index('s_stack_up = true;'):]
        self.assertRegex(ready, r'WIFI_REASON_NO_COPROCESSOR\)\s*set_state\(WIFI_SVC_CONNECTING, WIFI_REASON_NONE\)')


if __name__ == '__main__':
    unittest.main()
