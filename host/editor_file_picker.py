"""User-invoked native file picker; returns a path without opening the file."""
import sys
import tkinter as tk
from tkinter import filedialog

root = tk.Tk()
root.withdraw()
root.attributes('-topmost', True)
program = len(sys.argv) > 1 and sys.argv[1] == 'program'
path = filedialog.askopenfilename(parent=root, title='Choose program' if program else 'Choose file',
    filetypes=[('Programs', '*.exe *.lnk *.cmd *.bat'), ('All files', '*.*')] if program else [('All files', '*.*')])
root.destroy()
print(path)
