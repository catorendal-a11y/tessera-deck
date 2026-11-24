"""Questions to the user. Linux has no message box of its own and asks nothing on its own (platform_windows/dialogs.py has
the Windows one): the answer is always No. A notice goes to the desktop's notifications."""


def ask_yes_no(text: str, title: str = 'Tessera') -> bool:
    return False


def tell(text: str, title: str = 'Tessera') -> None:
    from platform_linux import notify
    notify.notify(text, title)
