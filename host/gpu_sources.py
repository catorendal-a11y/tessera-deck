"""GPU temperature, power, fan speed and clock without administrator rights or extra software.

NVIDIA cards are read through `nvidia-smi`, which ships with the driver; AMD cards on Windows through the driver's
own ADL library (platform_windows/gpu_adl.py). Libre Hardware Monitor or HWiNFO still win when they run
(see system_stats); these readers only fill in what would otherwise show "--".
"""
from __future__ import annotations

from platform_support import load
import shutil
import subprocess
from process_flags import NO_WINDOW
import time

NVIDIA_QUERY = 'temperature.gpu,power.draw,fan.speed,clocks.gr,utilization.gpu'
NVIDIA_CACHE_SECONDS = 2.0
NVIDIA_RETRY_SECONDS = 30.0


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
                             creationflags=NO_WINDOW)
            self._last = parse_nvidia(done.stdout) if done.returncode == 0 else {}
        except (OSError, subprocess.SubprocessError):
            self._last = {}
        if not self._last:  # a failing nvidia-smi is not started again every 2 seconds
            self._at = now + NVIDIA_RETRY_SECONDS - NVIDIA_CACHE_SECONDS
        return self._last


class GpuReaders:
    """The first reader that has something to say; a failing reader never stops the others."""

    def __init__(self, readers=None):
        if readers is None:
            readers = [NvidiaSmiReader(), *load('sensors').extra_gpu_readers()]
        self.readers = readers

    def sample(self) -> dict[str, float]:
        for reader in self.readers:
            try:
                values = reader.sample()
            except Exception:  # a driver hiccup must never take the status screen down
                continue
            if values:
                return values
        return {}
