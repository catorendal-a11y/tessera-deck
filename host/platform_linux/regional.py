"""The clock format of the system (the Windows counterpart reads the Region setting)."""


def clock_format() -> str:
    """'24h': the desktop's own setting is not read here."""
    return '24h'
