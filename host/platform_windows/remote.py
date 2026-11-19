"""Remote devices (KDE Connect) exist on Linux only; here the list is empty and controlling one says why."""

UNAVAILABLE = 'Remote devices need KDE Connect, which Tessera uses on Linux only.'


def list_devices() -> list[dict]:
    return []


def read_device(device: str) -> dict:
    raise OSError(UNAVAILABLE)


def write_volume(device: str, level: int) -> None:
    raise OSError(UNAVAILABLE)


def send_action(device: str, action: str) -> None:
    raise OSError(UNAVAILABLE)
