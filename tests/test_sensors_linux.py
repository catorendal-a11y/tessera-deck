"""Linux sensors from a fake /sys tree: hwmon temperatures, the amdgpu files and the fallbacks."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_marks import linux_only_module
linux_only_module(__name__)
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from platform_linux import sensors


def put(path: Path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text))


class FakeSys(tempfile.TemporaryDirectory):
    def __enter__(self):
        root = Path(super().__enter__())
        self.hwmon, self.drm = root / 'hwmon', root / 'drm'
        return self


class HwmonTests(unittest.TestCase):
    def test_the_cpu_temperature_comes_from_the_best_chip_and_label(self):
        with FakeSys() as fake:
            put(fake.hwmon / 'hwmon0/name', 'acpitz')
            put(fake.hwmon / 'hwmon0/temp1_input', 30000)
            put(fake.hwmon / 'hwmon1/name', 'k10temp')
            put(fake.hwmon / 'hwmon1/temp1_label', 'Tctl')
            put(fake.hwmon / 'hwmon1/temp1_input', 57625)
            put(fake.hwmon / 'hwmon1/temp3_label', 'Tccd1')
            put(fake.hwmon / 'hwmon1/temp3_input', 50000)
            self.assertEqual(sensors.cpu_temperature(sensors.hwmon_by_name(fake.hwmon)), 57.625)

    def test_without_a_known_label_temp1_is_used_and_without_a_chip_nothing(self):
        with FakeSys() as fake:
            put(fake.hwmon / 'hwmon0/name', 'coretemp')
            put(fake.hwmon / 'hwmon0/temp1_input', 61000)
            self.assertEqual(sensors.cpu_temperature(sensors.hwmon_by_name(fake.hwmon)), 61.0)
        self.assertIsNone(sensors.cpu_temperature({}))


class AmdTests(unittest.TestCase):
    def test_an_amd_card_gives_temperature_power_clock_load_and_vram(self):
        with FakeSys() as fake:
            put(fake.hwmon / 'hwmon0/name', 'amdgpu')
            put(fake.hwmon / 'hwmon0/temp1_input', 55000)
            put(fake.hwmon / 'hwmon0/power1_average', 17_030_000)
            put(fake.hwmon / 'hwmon0/freq1_input', 800_000_000)
            put(fake.hwmon / 'hwmon0/fan1_input', 1200)
            put(fake.drm / 'card1/device/gpu_busy_percent', 52)
            put(fake.drm / 'card1/device/mem_info_vram_used', 2 * 1024 ** 3)
            put(fake.drm / 'card1/device/mem_info_vram_total', 8 * 1024 ** 3)
            got = sensors.amd_gpu(fake.drm, sensors.hwmon_by_name(fake.hwmon))
        self.assertEqual(got, {'gpu_temp': 55.0, 'gpu_power': 17.03, 'gpu_clock': 800.0, 'gpu_fan': 1200.0, 'gpu_load': 52.0,
                               'vram': 25.0, 'vram_used_gb': 2.0})

    def test_a_machine_without_a_card_gives_nothing(self):
        with FakeSys() as fake:
            self.assertEqual(sensors.amd_gpu(fake.drm, {}), {})

    def test_the_whole_sample_merges_cpu_and_gpu_and_leaves_out_what_is_missing(self):
        with FakeSys() as fake:
            put(fake.hwmon / 'hwmon0/name', 'k10temp')
            put(fake.hwmon / 'hwmon0/temp1_input', 40000)
            reader = sensors.LinuxSensors(gpu=type('G', (), {'sample': lambda self: {'gpu_load': 9.0}})(),
                                          hwmon=lambda: sensors.hwmon_by_name(fake.hwmon), drm=fake.drm)
            got = reader.sample()
        self.assertEqual(got['cpu_temp'], 40.0)
        self.assertEqual(got['gpu_load'], 9.0)  # the NVIDIA reader answered first
        self.assertNotIn('gpu_temp', got)


class StatusSourcesTests(unittest.TestCase):
    """What the shared SystemStats asks of every system, answered for Linux."""

    def test_the_status_screen_reads_native_counters_and_the_root_disk(self):
        self.assertTrue(sensors.NATIVE_SENSORS)
        self.assertEqual(sensors.disk_root(), '/')
        self.assertEqual(sensors.extra_gpu_readers(), [])
        self.assertTrue(callable(sensors.native_counters().sample))

    def test_hwinfo_is_a_windows_program_and_gives_no_readings(self):
        self.assertEqual(sensors.hwinfo_reader().read(), [])

    def test_system_stats_uses_them(self):
        from system_stats import SystemStats
        stats = SystemStats(lhm=type('Silent', (), {'read': lambda self: []})())
        self.assertTrue(stats.native_sensors)
        self.assertIsInstance(stats.counters, sensors.LinuxSensors)


if __name__ == '__main__':
    unittest.main()
