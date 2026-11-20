"""Regional settings on Windows."""


def clock_format() -> str:
    """'12h' when Windows shows the time with AM/PM (Region settings), else '24h'. ImportError off Windows."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Control Panel\International') as key:
        return '12h' if str(winreg.QueryValueEx(key, 'iTime')[0]) == '0' else '24h'
