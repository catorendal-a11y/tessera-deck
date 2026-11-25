"""AMD graphics cards on Windows: temperatures, power, fan, clock and core voltage from the driver's own ADL library.

The same numbers Radeon Software shows, read without administrator rights. Nothing is written to the card.
"""
from __future__ import annotations

import ctypes
import os

# Slots of the ADL "PMLog" sensor block (ADL_PMLOG_*): which entry carries which reading.
PMLOG_GFX_CLOCK, PMLOG_EDGE_TEMP, PMLOG_FAN_RPM, PMLOG_ACTIVITY, PMLOG_ASIC_POWER, PMLOG_HOTSPOT_TEMP = 1, 8, 14, 19, 23, 27


PMLOG_FAN_PERCENT = 15
PMLOG_GFX_VOLTAGE = 21  # the core rail, in millivolts
# Cards from the RX 7000 series on report the power of the whole board here and leave PMLOG_ASIC_POWER out
# (ADL_PMLOG_BOARD_POWER in AMD's adl_defines.h; Libre Hardware Monitor reads the same slot for them).
PMLOG_BOARD_POWER = 73


PMLOG_SLOTS = 256


def card_power(sensors: dict[int, int]) -> int | None:
    """Watts the card draws: the board's reading where the card has one, else the chip's."""
    return sensors.get(PMLOG_BOARD_POWER, sensors.get(PMLOG_ASIC_POWER))


def parse_pmlog(sensors: dict[int, int]) -> dict[str, float]:
    """Readings from the supported PMLog slots (slot -> value) of one adapter."""
    result: dict[str, float] = {}
    temp = sensors.get(PMLOG_EDGE_TEMP, sensors.get(PMLOG_HOTSPOT_TEMP))
    if temp is not None and 0 < temp < 150:
        result['gpu_temp'] = float(temp)
    power = card_power(sensors)
    if power is not None:
        result['gpu_power'] = float(power)
    if PMLOG_GFX_CLOCK in sensors:
        result['gpu_clock'] = float(sensors[PMLOG_GFX_CLOCK])
    if PMLOG_FAN_RPM in sensors:
        result['gpu_fan'] = float(sensors[PMLOG_FAN_RPM])
    if PMLOG_ACTIVITY in sensors:
        result['gpu_load'] = float(sensors[PMLOG_ACTIVITY])
    hotspot = sensors.get(PMLOG_HOTSPOT_TEMP)
    if hotspot is not None and 0 < hotspot < 150:
        result['gpu_hotspot'] = float(hotspot)
    if PMLOG_GFX_VOLTAGE in sensors:
        result['gpu_volt'] = float(sensors[PMLOG_GFX_VOLTAGE])
    return result


def pick_graphics_card(adapters: dict[int, dict[int, int]]) -> int | None:
    """The discrete card among adapter index -> PMLog slots: the one with a fan, else the most power-hungry."""
    with_fan = [index for index, slots in adapters.items() if PMLOG_FAN_RPM in slots or PMLOG_FAN_PERCENT in slots]
    if with_fan:
        return max(with_fan, key=lambda index: card_power(adapters[index]) or 0)
    return max(adapters, key=lambda index: card_power(adapters[index]) or 0, default=None)


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
