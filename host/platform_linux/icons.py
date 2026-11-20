"""The icon of a program of the application menu (the Windows counterpart is platform_windows/icons.py)."""


def program_icon_image(target):
    from platform_linux import programs
    return programs.icon_image(target)
