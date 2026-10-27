"""GPU temperature, power, fan speed and clock without administrator rights or extra software.

AMD cards are read through the driver's own ADL library (the same numbers Radeon Software shows), NVIDIA cards
through `nvidia-smi`, which ships with the driver. Libre Hardware Monitor or HWiNFO still win when they run
(see system_stats); these readers only fill in what would otherwise show "--".
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import time

# Slots of the ADL "PMLog" sensor block (ADL_PMLOG_*): which entry carries which reading.
PMLOG_GFX_CLOCK, PMLOG_EDGE_TEMP, PMLOG_FAN_RPM, PMLOG_ACTIVITY, PMLOG_ASIC_POWER, PMLOG_HOTSPOT_TEMP = 1, 8, 14, 19, 23, 27
PMLOG_FAN_PERCENT = 15
PMLOG_SLOTS = 256
NVIDIA_QUERY = 'temperature.gpu,power.draw,fan.speed,clocks.gr,utilization.gpu'
NVIDIA_CACHE_SECONDS = 2.0


def parse_pmlog(sensors: dict[int, int]) -> dict[str, float]:
    """Readings from the supported PMLog slots (slot -> value) of one adapter."""
    result: dict[str, float] = {}
    temp = sensors.get(PMLOG_EDGE_TEMP, sensors.get(PMLOG_HOTSPOT_TEMP))
    if temp is not None and 0 < temp < 150:
        result['gpu_temp'] = float(temp)
    if PMLOG_ASIC_POWER in sensors:
        result['gpu_power'] = float(sensors[PMLOG_ASIC_POWER])
    if PMLOG_GFX_CLOCK in sensors:
        result['gpu_clock'] = float(sensors[PMLOG_GFX_CLOCK])
    if PMLOG_FAN_RPM in sensors:
        result['gpu_fan'] = float(sensors[PMLOG_FAN_RPM])
    if PMLOG_ACTIVITY in sensors:
        result['gpu_load'] = float(sensors[PMLOG_ACTIVITY])
    return result


def pick_graphics_card(adapters: dict[int, dict[int, int]]) -> int | None:
    """The discrete card among adapter index -> PMLog slots: the one with a fan, else the most power-hungry."""
    with_fan = [index for index, slots in adapters.items() if PMLOG_FAN_RPM in slots or PMLOG_FAN_PERCENT in slots]
    if with_fan:
        return max(with_fan, key=lambda index: adapters[index].get(PMLOG_ASIC_POWER, 0))
    return max(adapters, key=lambda index: adapters[index].get(PMLOG_ASIC_POWER, 0), default=None)


def parse_nvidia(text: str) -> dict[str, float]:
    """One line of `nvidia-smi --query-gpu=... --format=csv,noheader,nounits`; "[N/A]" fields are skipped."""
    names = ('gpu_temp', 'gpu_power', 'gpu_fan_percent', 'gpu_clock', 'gpu_load')
    line = next((row for row in text.strip().splitlines() if row.strip()), '')
    result: dict[str, float] = {}
    for name, field in zip(names, (part.strip() for part in line.split(',')), strict=False):
        try:
            result[name] = float(field)
        except ValueError:
            continue
    result.pop('gpu_fan_percent', None)  # a percentage is not the RPM the gauges show
    return result


class AdlReader:
    """AMD: temperature, power, fan and clock from ADL2_New_QueryPMLogData_Get. Nothing is written to the card."""

    def __init__(self):
        self._library = None
        self._context = ctypes.c_void_p()
        self._adapters: list[int] = []
        self._card: int | None = None
        self._failed = os.name != 'nt'
        self._malloc = None
        self._heap: list = []

    def _start(self) -> bool:
        if self._library is not None:
            return True
        if self._failed:
            return False
        try:
            library = ctypes.WinDLL('atiadlxx.dll')
            allocator = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_int)

            def malloc(size):
                buffer = ctypes.create_string_buffer(size)
                self._heap.append(buffer)
                return ctypes.addressof(buffer)
            self._malloc = allocator(malloc)
            if library.ADL2_Main_Control_Create(self._malloc, 1, ctypes.byref(self._context)) != 0:
                raise OSError('ADL could not start')
            self._adapters = self._enumerate(library)
            self._library = library
        except (OSError, AttributeError):
            self._failed = True
            return False
        return True

    def _enumerate(self, library) -> list[int]:
        class AdapterInfo(ctypes.Structure):
            _fields_ = [('iSize', ctypes.c_int), ('iAdapterIndex', ctypes.c_int), ('strUDID', ctypes.c_char * 256),
                        ('iBusNumber', ctypes.c_int), ('iDeviceNumber', ctypes.c_int), ('iFunctionNumber', ctypes.c_int),
                        ('iVendorID', ctypes.c_int), ('strAdapterName', ctypes.c_char * 256),
                        ('strDisplayName', ctypes.c_char * 256), ('iPresent', ctypes.c_int), ('iExist', ctypes.c_int),
                        ('strDriverPath', ctypes.c_char * 256), ('strDriverPathExt', ctypes.c_char * 256),
                        ('strPNPString', ctypes.c_char * 256), ('iOSDisplayIndex', ctypes.c_int)]
        count = ctypes.c_int()
        if library.ADL2_Adapter_NumberOfAdapters_Get(self._context, ctypes.byref(count)) != 0 or count.value <= 0:
            return []
        infos = (AdapterInfo * count.value)()
        if library.ADL2_Adapter_AdapterInfo_Get(self._context, infos, ctypes.sizeof(infos)) != 0:
            return []
        first_per_bus: dict[int, int] = {}
        for info in infos:  # one adapter entry per display output; one per physical card is enough
            first_per_bus.setdefault(info.iBusNumber, info.iAdapterIndex)
        return list(first_per_bus.values())

    def _pmlog(self, index: int) -> dict[int, int]:
        class Sensor(ctypes.Structure):
            _fields_ = [('supported', ctypes.c_int), ('value', ctypes.c_int)]

        class PMLog(ctypes.Structure):
            _fields_ = [('size', ctypes.c_int), ('sensors', Sensor * PMLOG_SLOTS)]
        block = PMLog()
        block.size = ctypes.sizeof(block)
        if self._library.ADL2_New_QueryPMLogData_Get(self._context, index, ctypes.byref(block)) != 0:
            return {}
        return {slot: sensor.value for slot, sensor in enumerate(block.sensors) if sensor.supported}

    def sample(self) -> dict[str, float]:
        if not self._start():
            return {}
        try:
            if self._card is None:
                found = {index: self._pmlog(index) for index in self._adapters}
                self._card = pick_graphics_card({index: slots for index, slots in found.items() if slots})
                if self._card is None:
                    return {}
            return parse_pmlog(self._pmlog(self._card))
        except (OSError, AttributeError, ctypes.ArgumentError):
            self._failed, self._library = True, None
            return {}


class NvidiaSmiReader:
    """NVIDIA: `nvidia-smi` is asked at most once every two seconds."""

    def __init__(self, run=subprocess.run, which=shutil.which, clock=time.monotonic):
        self._run, self._which, self._clock = run, which, clock
        self._path = None
        self._checked = False
        self._at = float('-inf')
        self._last: dict[str, float] = {}

    def sample(self) -> dict[str, float]:
        if not self._checked:
            self._path, self._checked = self._which('nvidia-smi'), True
        if not self._path:
            return {}
        now = self._clock()
        if now - self._at < NVIDIA_CACHE_SECONDS:
            return self._last
        self._at = now
        try:
            done = self._run([self._path, f'--query-gpu={NVIDIA_QUERY}', '--format=csv,noheader,nounits'],
                             capture_output=True, text=True, timeout=3, check=False,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self._last = parse_nvidia(done.stdout) if done.returncode == 0 else {}
        except (OSError, subprocess.SubprocessError):
            self._last = {}
        return self._last


class GpuReaders:
    """The first reader that has something to say; a failing reader never stops the others."""

    def __init__(self, readers=None):
        self.readers = readers if readers is not None else [NvidiaSmiReader(), AdlReader()]

    def sample(self) -> dict[str, float]:
        for reader in self.readers:
            try:
                values = reader.sample()
            except Exception:  # a driver hiccup must never take the status screen down
                continue
            if values:
                return values
        return {}
