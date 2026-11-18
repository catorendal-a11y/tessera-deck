"""Where the project's own Python lives: Windows keeps it in .venv/Scripts."""
from pathlib import Path

from platform_support import load

SCRIPTS = load('labels').VENV_SCRIPTS


def venv_python(root: Path, windowless: bool = False) -> Path:
    """The venv's python; on Windows `windowless` picks pythonw.exe (no console window)."""
    labels = load('labels')
    return Path(root) / 'host/.venv' / labels.VENV_SCRIPTS / (labels.VENV_PYTHON_WINDOWLESS if windowless else labels.VENV_PYTHON)
