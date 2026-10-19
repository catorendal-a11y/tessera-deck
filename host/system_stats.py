"""Live Windows and HWiNFO sensor values for Agent Deck."""
from __future__ import annotations

import ctypes
import os
import struct
import time

import psutil


def _text(raw: bytes) -> str:
    raw = raw.split(b'\0', 1)[0]
    for encoding in ('utf-8', 'cp1252'):
        try:
            return raw.decode(encoding).strip()
        except UnicodeDecodeError:
            pass
    return raw.decode('utf-8', 'replace').strip()


class HWiNFOReader:
    """Read the documented HWiNFO shared-memory sensor table."""

    MAP_NAME = 'Global\\HWiNFO_SENS_SM2'
    FILE_MAP_READ = 0x0004

    def read(self) -> list[dict]:
        if os.name != 'nt':
            return []
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_bool,
                                               ctypes.c_wchar_p]
        kernel32.OpenFileMappingW.restype = ctypes.c_void_p
        kernel32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                           ctypes.c_uint32, ctypes.c_uint32,
                                           ctypes.c_size_t]
        kernel32.MapViewOfFile.restype = ctypes.c_void_p
        kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenFileMappingW(self.FILE_MAP_READ, False, self.MAP_NAME)
        if not handle:
            return []
        view = None
        try:
            view = kernel32.MapViewOfFile(handle, self.FILE_MAP_READ, 0, 0, 0)
            if not view:
                return []
            header = ctypes.string_at(view, 48)
            if header[:4] != b'HWiS':
                return []
            (_, _, _, _, sensor_offset, sensor_size, sensor_count,
             reading_offset, reading_size, reading_count, _) = struct.unpack(
                 '<IIIqIIIIIII', header)
            if not (264 <= sensor_size <= 4096 and 316 <= reading_size <= 4096
                    and sensor_count <= 4096 and reading_count <= 65536):
                return []
            total = max(sensor_offset + sensor_size * sensor_count,
                        reading_offset + reading_size * reading_count)
            if total > 32 * 1024 * 1024:
                return []
            data = ctypes.string_at(view, total)
            sensors = []
            for index in range(sensor_count):
                offset = sensor_offset + index * sensor_size
                original = _text(data[offset + 8:offset + 136])
                user = _text(data[offset + 136:offset + 264])
                sensors.append(user or original)
            result = []
            for index in range(reading_count):
                offset = reading_offset + index * reading_size
                kind, sensor_index, reading_id = struct.unpack_from('<III', data, offset)
                original = _text(data[offset + 12:offset + 140])
                user = _text(data[offset + 140:offset + 268])
                unit = _text(data[offset + 268:offset + 284])
                current, minimum, maximum, average = struct.unpack_from('<dddd', data, offset + 284)
                result.append({
                    'type': kind,
                    'sensor': sensors[sensor_index] if sensor_index < len(sensors) else '',
                    'id': reading_id,
                    'label': user or original,
                    'unit': unit,
                    'value': current,
                    'min': minimum,
                    'max': maximum,
                    'avg': average,
                })
            return result
        finally:
            if view:
                kernel32.UnmapViewOfFile(view)
            kernel32.CloseHandle(handle)


def _norm(value: str) -> str:
    return value.casefold().replace('°', '').strip()


def select_hwinfo_metrics(readings: list[dict]) -> dict[str, float]:
    """Pick stable desktop metrics from HWiNFO's hardware-specific labels."""
    specs = {
        'cpu_temp': (('cpu (tctl/tdie)', 'cpu die (average)', 'cpu package',
                      'core temperatures', 'cpu die'), ('cpu', 'ryzen'), ('c',)),
        'cpu_power': (('cpu package power', 'cpu ppt', 'package power'),
                      ('cpu', 'ryzen'), ('w',)),
        'cpu_clock': (('core effective clocks', 'core clocks', 'cpu clock'),
                      ('cpu', 'ryzen'), ('mhz',)),
        'gpu_temp': (('gpu temperature', 'gpu hotspot temperature', 'gpu hot spot'),
                      ('gpu', 'radeon', '6950'), ('c',)),
        'gpu_load': (('gpu core load', 'gpu utilization', 'gpu d3d usage'),
                      ('gpu', 'radeon', '6950'), ('%',)),
        'gpu_power': (('gpu power', 'gpu asic power', 'total graphics power'),
                       ('gpu', 'radeon', '6950'), ('w',)),
        'gpu_clock': (('gpu clock', 'gpu effective clock'),
                       ('gpu', 'radeon', '6950'), ('mhz',)),
        'gpu_fan': (('gpu fan', 'fan speed'), ('gpu', 'radeon', '6950'), ('rpm',)),
        'vram': (('gpu memory usage', 'gpu memory utilization', 'vram usage'),
                  ('gpu', 'radeon', '6950'), ('%',)),
    }
    selected = {}
    for key, (labels, sensors, units) in specs.items():
        best = None
        for item in readings:
            label = _norm(str(item.get('label', '')))
            sensor = _norm(str(item.get('sensor', '')))
            unit = _norm(str(item.get('unit', '')))
            label_rank = next((len(labels) - i for i, name in enumerate(labels)
                               if label == name or name in label), 0)
            if not label_rank or unit not in units:
                continue
            sensor_rank = sum(term in sensor for term in sensors)
            # Prefer the discrete RX 6950 XT over the integrated Radeon GPU.
            discrete_bonus = 4 if ('6950' in sensor or 'rx 6' in sensor) else 0
            score = label_rank * 10 + sensor_rank + discrete_bonus
            if best is None or score > best[0]:
                best = (score, float(item['value']))
        if best is not None:
            selected[key] = best[1]
    return selected


def _rate(value: float) -> str:
    if value >= 1024 * 1024:
        return f'{value / 1024 / 1024:.1f}M'
    if value >= 1024:
        return f'{value / 1024:.0f}K'
    return f'{value:.0f}B'


def _uptime(seconds: float) -> str:
    days, remainder = divmod(max(0, int(seconds)), 86400)
    hours, minutes = divmod(remainder, 3600)[0], (remainder % 3600) // 60
    return f'{days}d {hours}t' if days else f'{hours}t {minutes}m'


class SystemStats:
    def __init__(self, hwinfo=None):
        self.hwinfo = hwinfo or HWiNFOReader()
        self.raw: dict[str, float] = {}
        self.display = {key: '--' for key in (
            'cpu_temp', 'cpu_load', 'cpu_power', 'cpu_clock', 'gpu_temp',
            'gpu_load', 'gpu_power', 'gpu_clock', 'gpu_fan', 'ram', 'vram',
            'disk', 'net_down', 'net_up', 'uptime')}
        self.display['sensor_status'] = 'START'
        self._net = psutil.net_io_counters()
        self._net_at = time.monotonic()
        psutil.cpu_percent(None)

    def sample(self) -> dict[str, str]:
        now = time.monotonic()
        cpu = psutil.cpu_percent(None)
        ram = psutil.virtual_memory().percent
        drive = os.environ.get('SystemDrive', 'C:') + '\\'
        try:
            disk = psutil.disk_usage(drive).percent
        except OSError:
            disk = 0.0
        net = psutil.net_io_counters()
        elapsed = max(.1, now - self._net_at)
        down = max(0, net.bytes_recv - self._net.bytes_recv) / elapsed
        up = max(0, net.bytes_sent - self._net.bytes_sent) / elapsed
        self._net, self._net_at = net, now
        readings = self.hwinfo.read()
        sensor_values = select_hwinfo_metrics(readings)
        self.raw = dict(sensor_values, cpu_load=cpu, ram=ram, disk=disk,
                        net_down=down, net_up=up)
        for key in ('cpu_temp', 'cpu_load', 'cpu_power', 'gpu_temp', 'gpu_load',
                    'gpu_power', 'ram', 'vram', 'disk'):
            value = self.raw.get(key)
            self.display[key] = '--' if value is None else f'{value:.0f}'
        for key in ('cpu_clock', 'gpu_clock'):
            value = self.raw.get(key)
            self.display[key] = '--' if value is None else f'{value:.0f}'
        fan = self.raw.get('gpu_fan')
        self.display['gpu_fan'] = '--' if fan is None else f'{fan:.0f}'
        self.display['net_down'] = _rate(down)
        self.display['net_up'] = _rate(up)
        self.display['uptime'] = _uptime(time.time() - psutil.boot_time())
        self.display['sensor_status'] = 'LIVE' if readings else (
            'SETUPP' if self._hwinfo_running() else 'START')
        return dict(self.display)

    @staticmethod
    def _hwinfo_running() -> bool:
        try:
            return any((item.info.get('name') or '').lower().startswith('hwinfo')
                       for item in psutil.process_iter(['name']))
        except (psutil.Error, OSError):
            return False
