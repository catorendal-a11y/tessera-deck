"""Shared set-up for the host tests: the arguments of a test daemon and a daemon with a fake panel."""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import tesserad as deck  # noqa: E402


def args(path=ROOT / 'host/profiles.default.json'):
    return types.SimpleNamespace(profiles=str(path), port='TEST', verbose=False,
                                 no_focus=True, deck_only=True)


class HostCase(unittest.TestCase):
    def daemon(self, config=None):
        daemon = deck.Daemon(args())
        daemon.panel = Mock()
        daemon.log = Mock()
        daemon.publish_runtime = Mock()
        if config is not None:
            daemon.config = config
        return daemon
