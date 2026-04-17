import tkinter as tk
from ui.platform import FONT_FAMILY


class ToolTip:
    """Hover tooltip for any widget."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self._tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, event):
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        label = tk.Label(
            tw, text=self.text, justify=tk.LEFT,
            bg="#333333", fg="#e0e0e0", relief=tk.SOLID, borderwidth=1,
            font=(FONT_FAMILY, 9), padx=8, pady=6, wraplength=280,
        )
        label.pack()

    def _hide(self, _event):
        if self._tip:
            self._tip.destroy()
            self._tip = None
