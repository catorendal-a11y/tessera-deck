"""HWiNFO sensor values on Windows, read from HWiNFO's documented shared-memory table (Global\\HWiNFO_SENS_SM2)."""
from __future__ import annotations

import ctypes
import os
import struct


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
