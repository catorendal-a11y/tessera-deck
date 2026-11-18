"""What the shared setup and tray code says about Windows: names in messages and the Python modules the host needs."""
MODULE_PROBE = 'import serial, psutil, PIL, webview, win32pdh, pystray, comtypes, esptool'
AUTOSTART_NAME = 'Windows'  # "Start with Windows"
SHORTCUT_NAME = 'Desktop shortcut'
LAUNCHER = 'Tessera.cmd'
ASKS_ABOUT_AUTOSTART = True  # the tray asks once, at the first panel connection, whether to start with the system

# How a program is named and what a profile may hold
PROGRAM_SUFFIX = r'\.exe'  # a program name must end in .exe (spotify.exe)
PROGRAM_EXAMPLE = 'notepad.exe'
PROGRAM_LIST_NOTE = ' ending in .exe'
SCRIPT_EXTRA_SUFFIXES = ()  # script types beyond .py .pyw .ps1 .bat .cmd .ahk .js
DEFAULT_PROFILE = 'profiles.default.json'
DEFAULT_PORT = 'COM4'
RESETS_ON_OPEN = False  # opening the serial port does not reset the panel
PLUGIN_ENV_KEEP = ('PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA',
                   'PROGRAMDATA', 'HOMEDRIVE', 'HOMEPATH')  # what a plugin keeps of this process's environment
VENV_SCRIPTS = 'Scripts'
VENV_PYTHON = 'python.exe'
VENV_PYTHON_WINDOWLESS = 'pythonw.exe'
