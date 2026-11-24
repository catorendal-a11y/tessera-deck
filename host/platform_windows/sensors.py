"""Free sensor sources for the status screen: Windows counters and Libre Hardware Monitor.

WindowsCounters needs no extra software (works on AMD, Intel and NVIDIA GPUs).
LibreHardwareMonitorReader reads temperatures, power and fan speed from the free,
open-source Libre Hardware Monitor when its remote web server is running.
"""
from __future__ import annotations

import collections
import logging
import os
import re
import time

try:
    import win32pdh
except ImportError:  # pywin32 is optional; the status screen degrades gracefully
    win32pdh = None

log = logging.getLogger(__name__)
ENGINE_PATH = r'\GPU Engine(*)\Utilization Percentage'
MEMORY_PATH = r'\GPU Adapter Memory(*)\Dedicated Usage'
PERFORMANCE_PATH = r'\Processor Information(_Total)\% Processor Performance'
ENGINE_INSTANCE = re.compile(r'\(pid_\d+_luid_(0x[0-9A-Fa-f]+_0x[0-9A-Fa-f]+)_phys_\d+_eng_(\d+)_engtype_([^)]+)\)')
MEMORY_INSTANCE = re.compile(r'\(luid_(0x[0-9A-Fa-f]+_0x[0-9A-Fa-f]+)_phys_\d+\)')
RE_EXPAND_SECONDS = 60.0  # re-adding every GPU counter stalls the main loop ~170 ms
DISPLAY_CLASS_KEY = r'SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'


def total_vram_bytes() -> int:
    """Largest dedicated video memory among display adapters (the discrete GPU)."""
    if os.name != 'nt':
        return 0
    import winreg
    best = 0
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, DISPLAY_CLASS_KEY) as key:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(key, index)
                except OSError:
                    break
                index += 1
                if not name.isdigit():
                    continue
                try:
                    with winreg.OpenKey(key, name) as adapter:
                        value = winreg.QueryValueEx(adapter, 'HardwareInformation.qwMemorySize')[0]
                except OSError:
                    continue
                if isinstance(value, bytes):
                    value = int.from_bytes(value[:8], 'little')
                best = max(best, int(value))
    except OSError:
        return 0
    return best


def gpu_load_by_adapter(values: dict[str, float]) -> dict[str, float]:
    """Busiest engine per adapter, like Task Manager: sum over processes, max over engines."""
    sums = collections.defaultdict(float)
    for path, value in values.items():
        match = ENGINE_INSTANCE.search(path)
        if match:
            sums[match.groups()] += value
    loads: dict[str, float] = collections.defaultdict(float)
    for (luid, _engine, _kind), total in sums.items():
        loads[luid] = max(loads[luid], total)
    return {luid: min(100.0, load) for luid, load in loads.items()}


def memory_by_adapter(values: dict[str, float]) -> dict[str, float]:
    result = {}
    for path, value in values.items():
        match = MEMORY_INSTANCE.search(path)
        if match:
            result[match.group(1)] = value
    return result


class WindowsCounters:
    """GPU load, VRAM use and effective CPU clock from Windows performance counters."""

    def __init__(self, base_clock_mhz: float | None = None):
        self.base_clock = base_clock_mhz or 0.0
        self.total_vram = total_vram_bytes()
        self._query = None
        self._handles: dict[str, object] = {}
        self._performance = None
        self._expanded_at = 0.0
        self._last: dict[str, float] = {}  # shown while the counters are listed again, so the gauges do not blink

    @property
    def available(self) -> bool:
        return win32pdh is not None and os.name == 'nt'

    def _reset(self):
        if self._query is not None:
            try:
                win32pdh.CloseQuery(self._query)
            except Exception:
                pass
        self._query = win32pdh.OpenQuery()
        self._handles = {}
        for pattern in (ENGINE_PATH, MEMORY_PATH):
            # One wildcard counter per pattern, added by its English name. ExpandCounterPath takes the names in the
            # display language of Windows, so on a German or French Windows it would find nothing for these English
            # paths. AddEnglishCounter should find them there too, but that was only checked on English Windows.
            try:
                self._handles[pattern] = win32pdh.AddEnglishCounter(self._query, pattern)
            except Exception:
                log.debug('counter pattern %s unavailable', pattern, exc_info=True)
        try:
            self._performance = win32pdh.AddEnglishCounter(self._query, PERFORMANCE_PATH)
        except Exception:
            log.debug('CPU clock counter unavailable', exc_info=True)
            self._performance = None
        win32pdh.CollectQueryData(self._query)
        self._expanded_at = time.monotonic()

    def sample(self) -> dict[str, float]:
        if not self.available:
            return {}
        try:
            if self._query is None and self._expanded_at and time.monotonic() - self._expanded_at <= RE_EXPAND_SECONDS:
                return {}  # the counters failed a moment ago (see below): try again only after the interval
            if self._query is None or time.monotonic() - self._expanded_at > RE_EXPAND_SECONDS:
                self._reset()
                return dict(self._last)
            win32pdh.CollectQueryData(self._query)
            values = {}
            for pattern, handle in self._handles.items():
                try:
                    instances = win32pdh.GetFormattedCounterArray(handle, win32pdh.PDH_FMT_DOUBLE)
                except Exception:
                    continue
                for instance, value in instances.items():
                    values[pattern.replace('*', instance)] = value
            self._last = self._summarize(values)
            return dict(self._last)
        except Exception:
            # Close the half-built query (it would leak each poll) and wait RE_EXPAND_SECONDS before trying again:
            # a PC without these counters (a VM, a remote session) would otherwise expand them every second.
            if self._query is not None:
                try:
                    win32pdh.CloseQuery(self._query)
                except Exception:
                    pass
            self._query = None
            self._expanded_at = time.monotonic()
            return {}

    def _summarize(self, values: dict[str, float]) -> dict[str, float]:
        result: dict[str, float] = {}
        loads = gpu_load_by_adapter(values)
        memory = memory_by_adapter(values)
        if memory:
            luid = max(memory, key=memory.get)  # the adapter holding the most video memory
            if self.total_vram:
                result['vram'] = min(100.0, memory[luid] / self.total_vram * 100)
                result['vram_used_gb'] = memory[luid] / 1024 ** 3
            if luid in loads:
                result['gpu_load'] = loads[luid]
        if 'gpu_load' not in result and loads:
            result['gpu_load'] = max(loads.values())
        if self._performance is not None and self.base_clock:
            try:
                performance = win32pdh.GetFormattedCounterValue(self._performance, win32pdh.PDH_FMT_DOUBLE)[1]
                result['cpu_clock'] = self.base_clock * performance / 100
            except Exception:
                pass
        return result

from lhm_reader import LibreHardwareMonitorReader, flatten_sensor_tree, parse_value  # noqa: E402,F401  (kept here for the callers of this module)


# What the shared status code asks of every system (platform_linux/sensors.py has the same names)
NATIVE_SENSORS = False  # counters need a helper (Libre Hardware Monitor, HWiNFO) for temperatures


def native_counters(base_clock_mhz=None):
    """The counters that answer sample() for the status screen."""
    return WindowsCounters(base_clock_mhz)


def hwinfo_reader():
    from platform_windows.hwinfo import HWiNFOReader
    return HWiNFOReader()


def disk_root() -> str:
    """The drive the status screen reports as the disk."""
    return os.environ.get('SystemDrive', 'C:') + '\\'


def extra_gpu_readers() -> list:
    """GPU readers beyond nvidia-smi: AMD's own ADL library."""
    from platform_windows.gpu_adl import AdlReader
    return [AdlReader()]
