"""Which system a test is for. A test of Windows behaviour runs only on Windows, a test of Linux behaviour only on Linux,
and a test with no mark runs everywhere.

    @windows_only                     a test or a class of tests
    windows_only_module(__name__)     a whole file, at the top of it (before the file's other imports)
"""
import sys
import unittest

IS_WINDOWS = sys.platform == 'win32'
IS_LINUX = sys.platform.startswith('linux')

windows_only = unittest.skipUnless(IS_WINDOWS, 'Windows only')
linux_only = unittest.skipUnless(IS_LINUX, 'Linux only')


def windows_only_module(name):
    if not IS_WINDOWS:
        raise unittest.SkipTest(f'{name} tests Windows behaviour')


def linux_only_module(name):
    if not IS_LINUX:
        raise unittest.SkipTest(f'{name} tests Linux behaviour')
