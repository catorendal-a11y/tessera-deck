"""What the shared setup and tray code says about Linux: names in messages and the Python modules the host needs."""
MODULE_PROBE = 'import serial, psutil, PIL, webview, pystray, keyring, jeepney, esptool'
AUTOSTART_NAME = 'the desktop'  # "Start with the desktop"
SHORTCUT_NAME = 'application menu entry'  # it is also what a launcher bar or a search finds
LAUNCHER = 'Tessera.sh'
ASKS_ABOUT_AUTOSTART = False  # the tray menu has the entry; nothing is asked on the first connection

# How a program is named and what a profile may hold
PROGRAM_SUFFIX = r'(?:\.exe)?'  # a program is its executable name (spotify); .exe is accepted and ignored
PROGRAM_EXAMPLE = 'firefox'
PROGRAM_LIST_NOTE = ''
SCRIPT_EXTRA_SUFFIXES = ('.sh',)
DEFAULT_PROFILE = 'profiles.default.linux.json'
DEFAULT_PORT = ''  # no fixed port name: the panel is found by its USB id
RESETS_ON_OPEN = True  # opening the serial port resets the panel (DTR)
PLUGIN_ENV_KEEP = ('PATH', 'TEMP', 'TMP')  # what a plugin keeps of this process's environment
VENV_SCRIPTS = 'bin'
VENV_PYTHON = 'python'
VENV_PYTHON_WINDOWLESS = 'python'
