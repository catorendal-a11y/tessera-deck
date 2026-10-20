"""Portable defaults: program discovery when install paths differ, and vendor-neutral GPU selection."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from program_locator import locate, program_roots
from system_stats import gpu_discrete_bonus, select_hwinfo_metrics


def touch(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'MZ')
    return str(path)


class LocatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.env = {'ProgramFiles': str(self.base / 'PF'), 'ProgramFiles(x86)': str(self.base / 'PF86'),
                    'LOCALAPPDATA': str(self.base / 'Local')}

    def find(self, target):
        return locate(target, self.env, registry=lambda name: None)

    def test_an_existing_path_is_returned_unchanged(self):
        exe = touch(self.base / 'Direct' / 'tool.exe')
        self.assertEqual(self.find(exe), exe)

    def test_a_program_moved_to_another_program_root_is_found_by_its_relative_path(self):
        moved = touch(self.base / 'PF86' / 'TsSteam' / 'tssteam.exe')
        self.assertEqual(self.find(r'C:\Program Files\TsSteam\tssteam.exe'), moved)

    def test_a_per_user_install_is_found(self):
        user = touch(self.base / 'Local' / 'Programs' / 'TsUnity Hub' / 'TsUnity Hub.exe')
        self.assertEqual(self.find(r'C:\Program Files\TsUnity Hub\TsUnity Hub.exe'), user)

    def test_a_newer_version_folder_is_found_and_the_newest_wins(self):
        touch(self.base / 'PF' / 'TsKiCad' / '9.0' / 'bin' / 'tskicad.exe')
        newest = touch(self.base / 'PF' / 'TsKiCad' / '10.1' / 'bin' / 'tskicad.exe')
        self.assertEqual(self.find(r'C:\Program Files\TsKiCad\10.0\bin\tskicad.exe'), newest)

    def test_office_style_version_folders_match(self):
        office = touch(self.base / 'PF' / 'Ts Office' / 'root' / 'Office17' / 'TSWORD.EXE')
        self.assertEqual(self.find(r'C:\Program Files\Ts Office\root\Office16\TSWORD.EXE'), office)

    def test_a_missing_program_and_non_program_targets_return_none(self):
        self.assertIsNone(self.find(r'C:\Program Files\Nothing\nothing.exe'))
        self.assertIsNone(self.find('https://example.com'))
        self.assertIsNone(self.find(''))

    def test_the_registry_answer_wins_over_guessing(self):
        elsewhere = touch(self.base / 'Elsewhere' / 'tschrome.exe')
        found = locate(r'C:\Program Files\TsGoogle\TsChrome\Application\tschrome.exe', self.env,
                       registry=lambda name: elsewhere if name == 'tschrome.exe' else None)
        self.assertEqual(found, elsewhere)

    def test_program_roots_have_no_duplicates(self):
        env = dict(self.env, ProgramW6432=self.env['ProgramFiles'])
        roots = [str(root) for root in program_roots(env)]
        self.assertEqual(len(roots), len(set(root.casefold() for root in roots)))
        self.assertIn(str(self.base / 'Local' / 'Programs'), roots)

    def test_default_profiles_no_longer_pin_the_c_drive(self):
        text = (ROOT / 'host/profiles.default.json').read_text(encoding='utf-8')
        self.assertNotIn('C:\\\\Program Files', text)
        self.assertIn('%ProgramFiles%', text)
        json.loads(text)


def reading(sensor, label, value, unit):
    return {'sensor': sensor, 'label': label, 'value': value, 'unit': unit}


class GpuSelectionTests(unittest.TestCase):
    def test_a_discrete_nvidia_card_beats_an_intel_integrated_gpu(self):
        readings = [reading('Intel(R) UHD Graphics gpu-intel-integrated/0', 'GPU Core', 20, '%'),
                    reading('NVIDIA GeForce RTX 4070 gpu-nvidia/0', 'GPU Core Load', 63, '%'),
                    reading('NVIDIA GeForce RTX 4070 gpu-nvidia/0', 'GPU Temperature', 58, 'C')]
        chosen = select_hwinfo_metrics(readings)
        self.assertEqual((chosen['gpu_load'], chosen['gpu_temp']), (63, 58))

    def test_an_amd_discrete_card_beats_ryzen_integrated_graphics_in_either_order(self):
        rx = reading('AMD Radeon RX 7800 XT gpu-amd/1', 'GPU Temperature', 61, 'C')
        igpu = reading('AMD Radeon(TM) Graphics gpu-amd/0', 'GPU Temperature', 40, 'C')
        self.assertEqual(select_hwinfo_metrics([igpu, rx])['gpu_temp'], 61)
        self.assertEqual(select_hwinfo_metrics([rx, igpu])['gpu_temp'], 61)

    def test_a_pc_with_only_integrated_graphics_still_reports_it(self):
        only = [reading('AMD Radeon(TM) Graphics gpu-amd/0', 'GPU Temperature', 44, 'C')]
        self.assertEqual(select_hwinfo_metrics(only)['gpu_temp'], 44)

    def test_missing_gpu_sensors_simply_leave_the_metric_out(self):
        cpu = [reading('Intel Core i7 cpu-intel/0', 'CPU Package', 55, 'C')]
        chosen = select_hwinfo_metrics(cpu)
        self.assertEqual(chosen['cpu_temp'], 55)
        self.assertNotIn('gpu_temp', chosen)
        self.assertNotIn('gpu_load', chosen)

    def test_cpu_metrics_come_from_the_cpu_chip_not_the_gpu(self):
        readings = [reading('NVIDIA GeForce RTX 3080 gpu-nvidia/0', 'GPU Package', 48, 'W'),
                    reading('Intel Core i9 cpu-intel/0', 'CPU Package', 27, 'W')]
        self.assertEqual(select_hwinfo_metrics(readings)['cpu_power'], 27)

    def test_discrete_bonus_ranking(self):
        self.assertGreater(gpu_discrete_bonus('geforce rtx 4090'), gpu_discrete_bonus('unknown gpu'))
        self.assertLess(gpu_discrete_bonus('uhd graphics'), 0)
        self.assertGreater(gpu_discrete_bonus('intel arc a770'), 0)


if __name__ == '__main__':
    unittest.main()
