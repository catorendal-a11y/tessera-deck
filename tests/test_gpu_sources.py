"""GPU readings that need no admin rights: AMD through ADL, NVIDIA through nvidia-smi, and how they fill the gaps."""
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import gpu_sources as gpu
from system_stats import SystemStats

# What an RX 6950 XT and the integrated graphics of a Ryzen reported on a real machine (slot -> value).
DISCRETE = {1: 0, 2: 2240, 8: 47, 14: 301, 15: 15, 19: 0, 20: 1, 21: 0, 23: 43, 27: 56, 40: 3, 41: 16}
INTEGRATED = {1: 600, 2: 3000, 3: 1200, 7: 100, 16: 1240, 17: 10, 18: 8, 19: 0, 21: 1105, 23: 25, 28: 38, 29: 42}


class AmdTests(unittest.TestCase):
    def test_the_slots_become_gauge_values(self):
        self.assertEqual(gpu.parse_pmlog(DISCRETE), {'gpu_temp': 47.0, 'gpu_power': 43.0, 'gpu_clock': 0.0,
                                                     'gpu_fan': 301.0, 'gpu_load': 0.0})

    def test_the_hotspot_stands_in_for_a_missing_edge_temperature_and_nonsense_is_ignored(self):
        self.assertEqual(gpu.parse_pmlog({27: 61})['gpu_temp'], 61.0)
        self.assertNotIn('gpu_temp', gpu.parse_pmlog({8: 0}))
        self.assertNotIn('gpu_temp', gpu.parse_pmlog({8: 9999}))
        self.assertEqual(gpu.parse_pmlog({}), {})

    def test_the_card_with_a_fan_wins_over_the_integrated_graphics(self):
        self.assertEqual(gpu.pick_graphics_card({0: INTEGRATED, 5: DISCRETE}), 5)

    def test_without_any_fan_the_most_power_hungry_adapter_is_used(self):
        self.assertEqual(gpu.pick_graphics_card({0: {23: 25}, 1: {23: 90}}), 1)
        self.assertIsNone(gpu.pick_graphics_card({}))


class NvidiaTests(unittest.TestCase):
    def test_a_line_from_nvidia_smi_is_read_and_unavailable_fields_are_skipped(self):
        self.assertEqual(gpu.parse_nvidia('61, 142.35, 38, 1920, 17\n'),
                         {'gpu_temp': 61.0, 'gpu_power': 142.35, 'gpu_clock': 1920.0, 'gpu_load': 17.0})
        self.assertEqual(gpu.parse_nvidia('55, [N/A], [N/A], 300, 0'),
                         {'gpu_temp': 55.0, 'gpu_clock': 300.0, 'gpu_load': 0.0})
        self.assertEqual(gpu.parse_nvidia(''), {})

    def reader(self, output='60, 100, 30, 1500, 10', code=0):
        run = Mock(return_value=types.SimpleNamespace(stdout=output, returncode=code))
        clock = Mock(side_effect=[0.0, 0.5, 5.0])
        return gpu.NvidiaSmiReader(run=run, which=lambda name: 'nvidia-smi.exe', clock=clock), run

    def test_nvidia_smi_is_asked_at_most_every_two_seconds(self):
        reader, run = self.reader()
        reader.sample()
        reader.sample()
        self.assertEqual(run.call_count, 1)
        reader.sample()
        self.assertEqual(run.call_count, 2)

    def test_no_tool_or_a_failing_tool_gives_nothing(self):
        self.assertEqual(gpu.NvidiaSmiReader(which=lambda name: None).sample(), {})
        reader, _ = self.reader(code=9)
        self.assertEqual(reader.sample(), {})
        broken = Mock(side_effect=subprocess.TimeoutExpired('nvidia-smi', 3))
        self.assertEqual(gpu.NvidiaSmiReader(run=broken, which=lambda name: 'x', clock=lambda: 0.0).sample(), {})


class CombinedTests(unittest.TestCase):
    def test_the_first_reader_with_an_answer_wins_and_a_crashing_reader_is_skipped(self):
        crashing, empty, good = Mock(), Mock(), Mock()
        crashing.sample.side_effect = RuntimeError('driver')
        empty.sample.return_value = {}
        good.sample.return_value = {'gpu_temp': 50.0}
        self.assertEqual(gpu.GpuReaders([crashing, empty, good]).sample(), {'gpu_temp': 50.0})
        self.assertEqual(gpu.GpuReaders([crashing, empty]).sample(), {})


class StatusScreenTests(unittest.TestCase):
    def stats(self, lhm_readings, gpu_values):
        lhm = Mock()
        lhm.read.return_value = lhm_readings
        hwinfo = Mock()
        hwinfo.read.return_value = []
        counters = Mock()
        counters.sample.return_value = {}
        reader = Mock()
        reader.sample.return_value = gpu_values
        return SystemStats(hwinfo=hwinfo, lhm=lhm, counters=counters, gpu=reader)

    def test_the_gpu_readers_fill_the_gauges_when_no_sensor_tool_runs(self):
        shown = self.stats([], {'gpu_temp': 47.0, 'gpu_power': 43.0, 'gpu_clock': 2000.0, 'gpu_fan': 301.0}).sample()
        self.assertEqual((shown['gpu_temp'], shown['gpu_power'], shown['gpu_clock'], shown['gpu_fan']),
                         ('47', '43', '2000', '301'))
        self.assertEqual(shown['cpu_temp'], '--')  # a CPU temperature really needs Libre Hardware Monitor
        self.assertEqual(shown['sensor_status'], 'BASIC')

    def test_a_value_reported_by_several_sources_does_not_stop_the_update(self):
        clock = {'type': 1, 'sensor': 'AMD Ryzen 7', 'id': 2, 'label': 'Cores (Average)', 'unit': 'MHz',
                 'value': 4100.0, 'min': 0, 'max': 0, 'avg': 0}
        stats = self.stats([clock], {'gpu_temp': 47.0, 'gpu_load': 3.0})
        stats.counters.sample.return_value = {'cpu_clock': 3900.0, 'gpu_load': 5.0, 'vram': 27.0}
        shown = stats.sample()
        self.assertEqual(shown['cpu_clock'], '4100')  # the sensor tool wins
        self.assertEqual((shown['gpu_load'], shown['vram'], shown['gpu_temp']), ('5', '27', '47'))  # counters beat the driver reader

    def test_a_running_sensor_tool_wins_over_the_fallback(self):
        reading = {'type': 1, 'sensor': 'AMD Radeon RX 6950 XT', 'id': 1, 'label': 'GPU Core', 'unit': '°C',
                   'value': 52.0, 'min': 0, 'max': 0, 'avg': 0}
        shown = self.stats([reading], {'gpu_temp': 47.0}).sample()
        self.assertEqual(shown['gpu_temp'], '52')
        self.assertEqual(shown['sensor_status'], 'LIVE')


class SensorHintTests(unittest.TestCase):
    """Without Libre Hardware Monitor the CPU temperature cannot be read; say how to fix that instead of showing "--"."""

    def hint(self, installed, readings):
        import system_stats
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / 'LibreHardwareMonitor.exe'
            if installed:
                exe.write_bytes(b'x')
            lhm, hwinfo, counters, reader = Mock(), Mock(), Mock(), Mock()
            lhm.read.return_value = readings
            hwinfo.read.return_value = []
            counters.sample.return_value = {}
            reader.sample.return_value = {}
            with patch.object(system_stats, 'LHM_EXE', exe):
                stats = SystemStats(hwinfo=hwinfo, lhm=lhm, counters=counters, gpu=reader)
                stats.sample()
                return stats.hint

    def test_installed_but_not_running_points_to_the_one_time_setup(self):
        self.assertIn('--sensors', self.hint(True, []))

    def test_not_installed_points_to_the_installer(self):
        self.assertIn('setup_sensors', self.hint(False, []))

    def test_a_running_sensor_tool_needs_no_hint(self):
        reading = {'type': 1, 'sensor': 'CPU', 'id': 1, 'label': 'Core', 'unit': 'C', 'value': 50.0, 'min': 0, 'max': 0, 'avg': 0}
        self.assertEqual(self.hint(True, [reading]), '')


if __name__ == '__main__':
    unittest.main()
