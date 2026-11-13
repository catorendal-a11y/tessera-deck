"""Shared set-up for the host tests: the arguments of a test daemon and a daemon with a fake panel.

A test daemon works on a copy of the default profiles in a temporary folder, so the icons, counters and timers it
writes land there and not in host/, and it reads no real Claude Code or Codex sessions.
"""
import atexit
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import agent_activity  # noqa: E402
import tesserad as deck  # noqa: E402

FOLDER = Path(tempfile.mkdtemp(prefix='tessera-tests-'))
atexit.register(shutil.rmtree, FOLDER, True)
PROFILES = FOLDER / 'profiles.default.json'
shutil.copyfile(ROOT / 'host/profiles.default.json', PROFILES)


def args(path=PROFILES, port='TEST', no_focus=True):
    return types.SimpleNamespace(profiles=str(path), port=port, verbose=False,
                                 no_focus=no_focus, deck_only=True)


def test_daemon(path=PROFILES, port='TEST', no_focus=True):
    daemon = deck.Daemon(args(path, port=port, no_focus=no_focus))
    daemon.activity = agent_activity.AgentActivity(FOLDER / 'claude', FOLDER / 'codex')
    return daemon


class HostCase(unittest.TestCase):
    def daemon(self, config=None):
        daemon = test_daemon()
        daemon.panel = Mock()
        daemon.log = Mock()
        daemon.publish_runtime = Mock()
        if config is not None:
            daemon.config = config
        return daemon
