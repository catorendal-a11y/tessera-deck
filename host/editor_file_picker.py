"""User-invoked native file picker; returns a path without opening the file."""
import sys

from platform_support import load
import tkinter as tk
from tkinter import filedialog

root = tk.Tk()
root.withdraw()
root.attributes('-topmost', True)
kind = sys.argv[1] if len(sys.argv) > 1 else 'file'
program = kind == 'program'
filetypes = {'program': [('Programs', '*.exe *.lnk *.cmd *.bat'), ('All files', '*.*')],
             'script': [('Scripts', '*.py *.pyw *.ps1 *.bat *.cmd *.ahk *.js' + ''.join(' *' + suffix for suffix in load('labels').SCRIPT_EXTRA_SUFFIXES)), ('All files', '*.*')]}
path = filedialog.askopenfilename(parent=root, title={'program': 'Choose program', 'script': 'Choose script'}.get(kind, 'Choose file'),
    filetypes=filetypes.get(kind, [('All files', '*.*')]))
root.destroy()
print(path)
