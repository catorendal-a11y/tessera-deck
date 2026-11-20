"""Reads Libre Hardware Monitor's remote web server (Options > Remote Web Server) and turns its data.json tree into
HWiNFO-style readings. It is plain HTTP and JSON, so it is shared: the Windows counters and Linux hwmon sit in the
platform packages."""
from __future__ import annotations

import http.client
import json
import re
import time
import urllib.parse

MAX_SENSOR_BYTES = 4 * 1024 * 1024
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
        self._connection = None  # kept open between reads: connecting took as long as the rest of the read

    def _fetch(self) -> bytes:
        parts = urllib.parse.urlsplit(self.url)
        reused = self._connection is not None
        connection = self._connection or http.client.HTTPConnection(parts.hostname, parts.port, timeout=self.timeout)
        self._connection = None
        try:
            connection.request('GET', parts.path)
            reply = connection.getresponse()
            body = reply.read(MAX_SENSOR_BYTES)
            if reply.status != 200:
                raise OSError(f'HTTP {reply.status}')
        except (OSError, http.client.HTTPException):
            connection.close()
            if reused:  # the tool closed the idle connection: that says nothing about whether it still runs
                return self._fetch()
            raise
        if reply.isclosed():
            self._connection = connection
        else:
            connection.close()
        return body

    def read(self) -> list[dict]:
        if time.monotonic() < self._retry_at:
            return []
        try:
            tree = json.loads(self._fetch())
        except (OSError, ValueError, http.client.HTTPException):
            self._retry_at = time.monotonic() + self.RETRY_SECONDS
            return []
        return flatten_sensor_tree(tree) if isinstance(tree, dict) else []
