"""Platform detection and cross-platform constants."""
import sys

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

# -- Font family --
if IS_WINDOWS:
    FONT_FAMILY = "Segoe UI"
elif IS_MACOS:
    FONT_FAMILY = "Helvetica Neue"
else:
    FONT_FAMILY = "sans-serif"

# -- Drag-and-drop availability --
HAS_DND = False
try:
    import tkinterdnd2  # noqa: F401
    # Verify tkdnd actually loads in the Tcl interpreter
    import tkinter as _tk
    _test = _tk.Tk()
    _test.withdraw()
    _test.tk.eval("package require tkdnd")
    _test.destroy()
    HAS_DND = True
except Exception:
    # Clean up the test window if it was created
    try:
        _test.destroy()  # noqa: F821
    except Exception:
        pass
