import sys

# Fix blurry fonts on Windows high-DPI displays
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

import tkinter as tk
from ui.platform import HAS_DND
if HAS_DND:
    from tkinterdnd2 import TkinterDnD
from ui.app_window import AppWindow


def main():
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    root.title("BGDrop")
    root.geometry("800x650")
    root.minsize(640, 520)
    root.resizable(True, True)
    root.configure(bg="#1e1e1e")

    AppWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
