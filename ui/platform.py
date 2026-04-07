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
    HAS_DND = True
except ImportError:
    pass
