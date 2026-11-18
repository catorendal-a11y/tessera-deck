"""Which default profile a first run starts from: the one this system names (platform labels), else the default."""
from pathlib import Path

from platform_support import load


def seed_path(folder) -> Path:
    folder = Path(folder)
    own = folder / load('labels').DEFAULT_PROFILE
    return own if own.is_file() else folder / 'profiles.default.json'
