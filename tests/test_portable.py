"""Portable defaults: program discovery when install paths differ, and vendor-neutral GPU selection."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_marks import windows_only_module
windows_only_module(__name__)
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from platform_windows.programs import locate, program_roots
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
        self.assertNotIn('C:\\\\', text)  # no drive-letter paths: the starter set opens programs by name
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


class VoltageAndHotSpotTests(unittest.TestCase):
    """Issue 47: CPU and GPU voltage and the GPU hot spot, named as Libre Hardware Monitor 0.9.6 and HWiNFO name them."""
    RYZEN = 'AMD Ryzen 7 8845HS w/ Radeon 780M Graphics amdcpu/0'
    RX = 'AMD Radeon RX 9070 gpu-amd/1'
    IGPU = 'AMD Radeon 780M Graphics gpu-amd/0'

    def test_the_cpu_voltage_comes_from_the_core_rail_in_millivolts(self):
        intel = [reading('Intel Core i7-12700K intelcpu/0', 'P-Core #1', 1.1, 'V'),
                 reading('Intel Core i7-12700K intelcpu/0', 'CPU Core', 1.234, 'V')]
        self.assertAlmostEqual(select_hwinfo_metrics(intel)['cpu_volt'], 1234)
        zen = [reading(self.RYZEN, 'SoC (SVI2 TFN)', 0.9, 'V'), reading(self.RYZEN, 'Core #1 VID', 1.3, 'V'),
               reading(self.RYZEN, 'Core (SVI2 TFN)', 1.25, 'V')]
        self.assertAlmostEqual(select_hwinfo_metrics(zen)['cpu_volt'], 1250)
        hwinfo = [reading('CPU [#0]: AMD Ryzen 7 5800X: Enhanced', 'CPU Core Voltage (SVI2 TFN)', 1.2, 'V')]
        self.assertAlmostEqual(select_hwinfo_metrics(hwinfo)['cpu_volt'], 1200)

    def test_core_vids_stand_in_and_a_cpu_without_a_core_voltage_has_none(self):
        self.assertAlmostEqual(select_hwinfo_metrics([reading(self.RYZEN, 'Core #1 VID', 1.1, 'V')])['cpu_volt'], 1100)
        none = [reading(self.RYZEN, 'Core (Tctl/Tdie)', 61, 'C'), reading(self.RYZEN, 'SoC (SVI2 TFN)', 0.9, 'V'),
                reading('Nuvoton NCT6798D lpc/nct6798d/0', 'Vcore', 1.3, 'V')]
        self.assertNotIn('cpu_volt', select_hwinfo_metrics(none))

    def test_core_vids_give_the_highest_one_since_the_cores_share_one_rail(self):
        vids = [reading(self.RYZEN, f'Core #{n} VID', volts, 'V') for n, volts in enumerate((0.9, 1.3, 1.1, 1.25), 1)]
        self.assertAlmostEqual(select_hwinfo_metrics(vids)['cpu_volt'], 1300)

    def test_zen_4_desktop_gives_the_measured_vddcr_but_never_the_soc_rail(self):
        raphael = 'AMD Ryzen 7 7700X amdcpu/0'  # no Core (SVI2 TFN) on Zen 4 and 5 desktop in Libre Hardware Monitor
        readings = [reading(raphael, 'VDDCR SoC', 1.3, 'V'), reading(raphael, 'Core #1 VID', 1.4, 'V'),
                    reading(raphael, 'VDDCR', 1.1, 'V')]
        self.assertAlmostEqual(select_hwinfo_metrics(readings)['cpu_volt'], 1100)
        self.assertNotIn('cpu_volt', select_hwinfo_metrics([reading(raphael, 'VDDCR SoC', 1.3, 'V')]))

    def test_the_gpu_voltage_is_the_core_rail_of_the_discrete_card(self):
        amd = [reading(self.IGPU, 'GPU Core', 1.0, 'V'), reading(self.RX, 'GPU Memory', 1.35, 'V'),
               reading(self.RX, 'GPU SoC', 0.75, 'V'), reading(self.RX, 'GPU Core', 0.85, 'V')]
        self.assertAlmostEqual(select_hwinfo_metrics(amd)['gpu_volt'], 850)
        nvidia = [reading('NVIDIA GeForce RTX 4070 gpu-nvidia/0', 'GPU Core Voltage', 0.925, 'V')]
        self.assertAlmostEqual(select_hwinfo_metrics(nvidia)['gpu_volt'], 925)

    def test_the_hot_spot_has_its_own_reading_and_stays_the_fallback_for_the_gpu_temperature(self):
        chosen = select_hwinfo_metrics([reading(self.RX, 'GPU Core', 60, 'C'), reading(self.RX, 'GPU Hot Spot', 78, 'C')])
        self.assertEqual((chosen['gpu_temp'], chosen['gpu_hotspot']), (60, 78))
        for label in ('GPU Hotspot Temperature', 'GPU Hot Spot Temperature'):  # HWiNFO
            chosen = select_hwinfo_metrics([reading('GPU [#0]: AMD Radeon RX 9070', label, 81, 'C')])
            self.assertEqual((chosen['gpu_hotspot'], chosen['gpu_temp']), (81, 81), label)


if __name__ == '__main__':
    unittest.main()
