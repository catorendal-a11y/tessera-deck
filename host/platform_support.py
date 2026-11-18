"""Which system the host runs on: the one place that reads `sys.platform`.

Tessera has one platform package, `platform_windows`. `load('name')` gives its module, and `IS_WINDOWS` says whether the
host really runs on Windows (a Windows library is then used; on a development machine the same code runs with mocks, as
the tests and the tools of the build do). Another system is a new `platform_<name>` package with the same modules, a
line in `detect`, and a decision in `NAME`.
"""
import sys


class UnsupportedPlatform(OSError):
    """Tessera has no support for this operating system."""


def detect(platform: str | None = None) -> str:
    """'windows' for a `sys.platform` value (this system's by default); any other system raises."""
    name = sys.platform if platform is None else platform
    if name == 'win32':
        return 'windows'
    raise UnsupportedPlatform(f"Tessera runs on Windows, not on '{name}'")


NAME = 'windows'  # the only package there is: another system loads it too, as it always did
IS_WINDOWS = sys.platform == 'win32'


def load(module: str):
    """The module of this system's package: load('autostart') is platform_windows.autostart."""
    import importlib
    return importlib.import_module(f"platform_{NAME}.{module}")
