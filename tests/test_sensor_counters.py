"""GPU load and video memory from Windows performance counters, without reading any real counter."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import sensor_sources as sensors

GIB = 1024 ** 3
A, B = '0x00000000_0x0000AAAA', '0x00000000_0x0000BBBB'


def engine(luid, pid, number, kind, ):
    return rf'\GPU Engine(pid_{pid}_luid_{luid}_phys_0_eng_{number}_engtype_{kind})\Utilization Percentage'


def memory(luid):
    return rf'\GPU Adapter Memory(luid_{luid}_phys_0)\Dedicated Usage'


class GpuLoadTests(unittest.TestCase):
    def test_processes_add_up_per_engine_and_the_busiest_engine_counts(self):
        values = {engine(A, 1, 0, '3D'): 30.0, engine(A, 2, 0, '3D'): 25.0, engine(A, 3, 1, 'Copy'): 70.0}
        self.assertEqual(sensors.gpu_load_by_adapter(values), {A: 70.0})

    def test_the_load_never_exceeds_one_hundred_percent(self):
        values = {engine(A, 1, 0, '3D'): 80.0, engine(A, 2, 0, '3D'): 60.0}
        self.assertEqual(sensors.gpu_load_by_adapter(values), {A: 100.0})

    def test_each_adapter_is_measured_on_its_own_and_unrelated_paths_are_ignored(self):
        values = {engine(A, 1, 0, '3D'): 10.0, engine(B, 1, 0, '3D'): 90.0, r'\Other(thing)\Value': 5.0}
        self.assertEqual(sensors.gpu_load_by_adapter(values), {A: 10.0, B: 90.0})

    def test_memory_is_read_per_adapter(self):
        self.assertEqual(sensors.memory_by_adapter({memory(A): 1.0, memory(B): 2.0, 'x': 3.0}), {A: 1.0, B: 2.0})


class SummaryTests(unittest.TestCase):
    def counters(self, total_vram):
        with patch.object(sensors, 'total_vram_bytes', return_value=total_vram):
            return sensors.WindowsCounters()

    def test_the_adapter_with_the_most_video_memory_supplies_load_and_vram(self):
        counters = self.counters(8 * GIB)
        values = {memory(A): 1 * GIB, memory(B): 4 * GIB, engine(A, 1, 0, '3D'): 90.0, engine(B, 1, 0, '3D'): 20.0}
        summary = counters._summarize(values)
        self.assertEqual(summary['gpu_load'], 20.0)
        self.assertAlmostEqual(summary['vram'], 50.0)
        self.assertAlmostEqual(summary['vram_used_gb'], 4.0)

    def test_without_memory_counters_the_busiest_adapter_is_used_and_vram_is_left_out(self):
        summary = self.counters(0)._summarize({engine(A, 1, 0, '3D'): 10.0, engine(B, 1, 0, '3D'): 40.0})
        self.assertEqual(summary, {'gpu_load': 40.0})

    def test_without_the_total_the_vram_percentage_is_not_guessed(self):
        summary = self.counters(0)._summarize({memory(A): 2 * GIB})
        self.assertNotIn('vram', summary)

    def test_nothing_is_sampled_when_the_counters_are_unavailable(self):
        counters = self.counters(0)
        with patch.object(sensors, 'win32pdh', None):
            self.assertEqual(counters.sample(), {})


class RefreshTests(unittest.TestCase):
    """Every 15 s the counters are re-listed; the gauges must keep the last values meanwhile instead of flashing "--"."""

    def counters(self):
        with patch.object(sensors, 'total_vram_bytes', return_value=0):
            counters = sensors.WindowsCounters()
        counters._query, counters._handles, counters._expanded_at = 'query', {}, 0.0
        counters._summarize = lambda values: {'vram': 27.0}
        counters._reset = Mock()
        return counters

    def test_the_last_values_survive_the_moment_the_counters_are_listed_again(self):
        counters = self.counters()
        with patch.object(sensors, 'win32pdh', Mock()), patch.object(sensors.time, 'monotonic', return_value=1.0):
            self.assertEqual(counters.sample(), {'vram': 27.0})
        counters._expanded_at = -1e9
        with patch.object(sensors, 'win32pdh', Mock()), patch.object(sensors.time, 'monotonic', return_value=1.0):
            self.assertEqual(counters.sample(), {'vram': 27.0})
        counters._reset.assert_called_once()

    def test_a_failing_query_keeps_the_last_values_for_one_round_only(self):
        counters = self.counters()
        counters._last = {'vram': 27.0}
        with patch.object(sensors, 'win32pdh') as pdh, patch.object(sensors.time, 'monotonic', return_value=1.0):
            pdh.CollectQueryData.side_effect = OSError('gone')
            self.assertEqual(counters.sample(), {})
        self.assertIsNone(counters._query)


if __name__ == '__main__':
    unittest.main()
