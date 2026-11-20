"""CPU and GPU readings on Linux from the kernel's own interfaces: hwmon, the amdgpu sysfs files, and nvidia-smi.

Stands in for Windows' performance counters and Libre Hardware Monitor. A value the machine does not have is left out,
and the status screen shows `--` for it. Nothing needs root; Intel's RAPL power counter is read when it is readable.
"""
from __future__ import annotations

from pathlib import Path
import time

import psutil

HWMON = Path('/sys/class/hwmon')
DRM = Path('/sys/class/drm')
CPU_CHIPS = ('k10temp', 'coretemp', 'zenpower', 'cpu_thermal', 'acpitz')  # best first
CPU_LABELS = ('tctl', 'package id 0', 'tdie', 'cpu')


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except (OSError, ValueError):
        return None


def _number(path: Path) -> float | None:
    text = _read(path)
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def hwmon_by_name(root: Path = HWMON) -> dict[str, Path]:
    found = {}
    try:
        for folder in sorted(root.glob('hwmon*')):
            name = _read(folder / 'name')
            if name and name not in found:
                found[name] = folder
    except OSError:
        pass
    return found


def cpu_temperature(chips: dict[str, Path]) -> float | None:
    for chip in CPU_CHIPS:
        folder = chips.get(chip)
        if folder is None:
            continue
        readings = {}
        for label_file in sorted(folder.glob('temp*_label')):
            value = _number(Path(str(label_file).replace('_label', '_input')))
            if value is not None:
                readings[(_read(label_file) or '').lower()] = value / 1000
        for label in CPU_LABELS:
            if label in readings:
                return readings[label]
        value = _number(folder / 'temp1_input')
        if value is not None:
            return value / 1000
    return None


def amd_gpu(root: Path = DRM, chips: dict[str, Path] | None = None) -> dict[str, float]:
    """Temperature, load, power, clock, fan and VRAM of the first AMD graphics card."""
    result: dict[str, float] = {}
    chips = chips if chips is not None else hwmon_by_name()
    folder = chips.get('amdgpu')
    if folder is not None:
        for key, name, scale in (('gpu_temp', 'temp1_input', 1000), ('gpu_power', 'power1_average', 1_000_000),
                                 ('gpu_clock', 'freq1_input', 1_000_000), ('gpu_fan', 'fan1_input', 1)):
            value = _number(folder / name)
            if value is None and key == 'gpu_power':
                value = _number(folder / 'power1_input')
            if value is not None:
                result[key] = value / scale
    try:
        cards = sorted(root.glob('card[0-9]*/device'))
    except OSError:
        cards = []
    for device in cards:
        load = _number(device / 'gpu_busy_percent')
        if load is None:
            continue
        result['gpu_load'] = load
        used, total = _number(device / 'mem_info_vram_used'), _number(device / 'mem_info_vram_total')
        if used is not None and total:
            result['vram'] = min(100.0, used / total * 100)
            result['vram_used_gb'] = used / 1024 ** 3
        break
    return result


class LinuxSensors:
    """sample() -> the readings the status screen shows; the same call the Windows counters answer."""

    def __init__(self, gpu=None, hwmon=hwmon_by_name, drm: Path = DRM):
        from gpu_sources import GpuReaders, NvidiaSmiReader
        self._hwmon, self._drm = hwmon, drm
        self._nvidia = gpu if gpu is not None else GpuReaders([NvidiaSmiReader()])
        self._rapl = None
        self._rapl_at = 0.0

    def sample(self) -> dict[str, float]:
        chips = self._hwmon()
        result: dict[str, float] = {}
        temperature = cpu_temperature(chips)
        if temperature is not None:
            result['cpu_temp'] = temperature
        frequency = psutil.cpu_freq()
        if frequency and frequency.current:
            result['cpu_clock'] = frequency.current
        power = self._cpu_power()
        if power is not None:
            result['cpu_power'] = power
        result.update(self._nvidia.sample())
        for key, value in amd_gpu(self._drm, chips).items():
            result.setdefault(key, value)
        return result

    def _cpu_power(self) -> float | None:
        """Watts from Intel's RAPL energy counter between two samples; None where it is missing or not readable."""
        counter = _number(Path('/sys/class/powercap/intel-rapl:0/energy_uj'))
        now = time.monotonic()
        previous, self._rapl, self._rapl_at = self._rapl, (counter, now), now
        if counter is None or previous is None or previous[0] is None or counter < previous[0]:
            return None
        elapsed = now - previous[1]
        return (counter - previous[0]) / 1_000_000 / elapsed if elapsed > 0 else None


# What the shared status code asks of every system (platform_windows/sensors.py has the same names)
NATIVE_SENSORS = True  # hwmon, the amdgpu files and nvidia-smi answer without a helper program


def native_counters(base_clock_mhz=None):
    """The counters that answer sample() for the status screen."""
    return LinuxSensors()


class _NoReadings:
    def read(self) -> list[dict]:
        return []


def hwinfo_reader():
    """HWiNFO is a Windows program: nothing to read here."""
    return _NoReadings()


def disk_root() -> str:
    return '/'


def extra_gpu_readers() -> list:
    return []
