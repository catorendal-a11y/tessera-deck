"""Free sensor sources for the status screen: Windows counters and Libre Hardware Monitor.

WindowsCounters needs no extra software (works on AMD, Intel and NVIDIA GPUs).
LibreHardwareMonitorReader reads temperatures, power and fan speed from the free,
open-source Libre Hardware Monitor when its remote web server is running.
"""
from __future__ import annotations

import collections
import json
import os
import re
import time
import urllib.error
import urllib.request

try:
    import win32pdh
except ImportError:  # pywin32 is optional; the status screen degrades gracefully
    win32pdh = None

ENGINE_PATH = r'\GPU Engine(*)\Utilization Percentage'
MEMORY_PATH = r'\GPU Adapter Memory(*)\Dedicated Usage'
PERFORMANCE_PATH = r'\Processor Information(_Total)\% Processor Performance'
ENGINE_INSTANCE = re.compile(r'\(pid_\d+_luid_(0x[0-9A-Fa-f]+_0x[0-9A-Fa-f]+)_phys_\d+_eng_(\d+)_engtype_([^)]+)\)')
MEMORY_INSTANCE = re.compile(r'\(luid_(0x[0-9A-Fa-f]+_0x[0-9A-Fa-f]+)_phys_\d+\)')
RE_EXPAND_SECONDS = 15.0
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
            try:
                paths = win32pdh.ExpandCounterPath(pattern)
            except Exception:
                paths = []
            for path in paths:
                try:
                    self._handles[path] = win32pdh.AddEnglishCounter(self._query, path)
                except Exception:
                    continue
        try:
            self._performance = win32pdh.AddEnglishCounter(self._query, PERFORMANCE_PATH)
        except Exception:
            self._performance = None
        win32pdh.CollectQueryData(self._query)
        self._expanded_at = time.monotonic()

    def sample(self) -> dict[str, float]:
        if not self.available:
            return {}
        try:
            if self._query is None or time.monotonic() - self._expanded_at > RE_EXPAND_SECONDS:
                self._reset()
                return dict(self._last)
            win32pdh.CollectQueryData(self._query)
            values = {}
            for path, handle in self._handles.items():
                try:
                    values[path] = win32pdh.GetFormattedCounterValue(handle, win32pdh.PDH_FMT_DOUBLE)[1]
                except Exception:
                    continue
            self._last = self._summarize(values)
            return dict(self._last)
        except Exception:
            self._query = None
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


VALUE = re.compile(r'^\s*(-?\d+(?:[.,]\d+)?)\s*(.*)$')
HARDWARE_DEPTH = 2  # Sensor > computer > hardware > sensor group > sensor


def parse_value(text: str):
    """'45.0 °C' -> (45.0, 'c'); returns None for non-numeric text."""
    match = VALUE.match(text or '')
    if not match:
        return None
    return float(match.group(1).replace(',', '.')), match.group(2).replace('°', '').strip().casefold()


def flatten_sensor_tree(node: dict, depth: int = 0, hardware: str = '') -> list[dict]:
    """Turn Libre Hardware Monitor's data.json tree into HWiNFO-style readings."""
    text = str(node.get('Text', ''))
    if depth == HARDWARE_DEPTH:
        hardware = text
    readings = []
    sensor_id = str(node.get('SensorId', ''))
    if sensor_id and 'Value' in node:
        parsed = parse_value(str(node['Value']))
        if parsed:
            kind = '/'.join(sensor_id.split('/')[1:3])  # e.g. 'amdcpu/0' or 'gpu-amd/0'
            readings.append({'label': text, 'sensor': f'{hardware} {kind}'.strip(), 'unit': parsed[1],
                             'value': parsed[0], 'id': sensor_id})
    for child in node.get('Children') or []:
        readings.extend(flatten_sensor_tree(child, depth + 1, hardware))
    return readings


class LibreHardwareMonitorReader:
    """Reads Libre Hardware Monitor's remote web server (Options > Remote Web Server)."""

    RETRY_SECONDS = 10.0

    def __init__(self, url: str = 'http://127.0.0.1:8085/data.json', timeout: float = 0.4):
        self.url = url
        self.timeout = timeout
        self._retry_at = 0.0

    def read(self) -> list[dict]:
        if time.monotonic() < self._retry_at:
            return []
        try:
            with urllib.request.urlopen(self.url, timeout=self.timeout) as reply:
                tree = json.loads(reply.read(4 * 1024 * 1024))
        except (OSError, ValueError, urllib.error.URLError):
            self._retry_at = time.monotonic() + self.RETRY_SECONDS
            return []
        return flatten_sensor_tree(tree) if isinstance(tree, dict) else []
