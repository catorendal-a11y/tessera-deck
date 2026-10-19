"""User-invoked native file picker; returns a path without opening the file."""
import sys
import tkinter as tk
from tkinter import filedialog

root = tk.Tk()
root.withdraw()
root.attributes('-topmost', True)
program = len(sys.argv) > 1 and sys.argv[1] == 'program'
path = filedialog.askopenfilename(parent=root, title='Velg program' if program else 'Velg fil',
    filetypes=[('Programmer', '*.exe *.lnk *.cmd *.bat'), ('Alle filer', '*.*')] if program else [('Alle filer', '*.*')])
root.destroy()
print(path)
