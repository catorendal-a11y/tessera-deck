"""Which default profile a first run starts from: the Linux one on Linux (when the folder has it), the Windows one else."""
from pathlib import Path

from platform_support import load


def seed_path(folder) -> Path:
    folder = Path(folder)
    own = folder / load('labels').DEFAULT_PROFILE
    return own if own.is_file() else folder / 'profiles.default.json'
