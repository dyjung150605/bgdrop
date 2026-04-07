"""Horizontal row of color-circle selectors for preview background."""
import tkinter as tk
from tkinter import colorchooser

# (key, display_color_or_None, label)
# None = checkerboard
BG_PRESETS = [
    ("checker", None, "Checker"),
    ("white", "#ffffff", "White"),
    ("black", "#000000", "Black"),
    ("chroma", "#00ff00", "Chroma"),
]

_CIRCLE_R = 9  # radius
_PAD = 3


class BgCombo(tk.Frame):
    """Row of colored circles. Click to select. Last circle = custom palette."""

    def __init__(self, parent, on_change=None, **kwargs):
        bg = kwargs.pop("bg", "#1e1e1e")
        super().__init__(parent, bg=bg, **kwargs)
        self._on_change = on_change
        self._selected = "checker"
        self._custom_color = None
        self._circles = {}  # key -> canvas

        for key, color, tip in BG_PRESETS:
            c = self._make_circle(key, color, tip)
            c.pack(side=tk.LEFT, padx=1)
            self._circles[key] = c

        # custom / palette circle
        c = self._make_circle("custom", "#888888", "Custom")
        c.pack(side=tk.LEFT, padx=1)
        self._circles["custom"] = c

        self._highlight_selected()

    def _make_circle(self, key, fill, tip):
        size = (_CIRCLE_R + _PAD) * 2
        c = tk.Canvas(self, width=size, height=size, bg=self.cget("bg"),
                      highlightthickness=0, cursor="hand2")
        cx = cy = _CIRCLE_R + _PAD
        r = _CIRCLE_R

        if fill is None:
            # mini checkerboard
            s = r - 1
            c.create_rectangle(cx - s, cy - s, cx, cy, fill="#ccc", outline="")
            c.create_rectangle(cx, cy, cx + s, cy + s, fill="#ccc", outline="")
            c.create_rectangle(cx, cy - s, cx + s, cy, fill="#fff", outline="")
            c.create_rectangle(cx - s, cy, cx, cy + s, fill="#fff", outline="")
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#888", width=1, tags="ring")
        elif key == "custom":
            # rainbow-ish gradient hint: just a multi-color split
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=0, extent=90,
                         fill="#ff4444", outline="")
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=90,
                         fill="#44ff44", outline="")
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=180, extent=90,
                         fill="#4444ff", outline="")
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=270, extent=90,
                         fill="#ffff44", outline="")
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#888", width=1, tags="ring")
        else:
            c.create_oval(cx - r, cy - r, cx + r, cy + r,
                          fill=fill, outline="#888", width=1, tags="ring")

        c.bind("<Button-1>", lambda e, k=key: self._on_click(k))
        return c

    @property
    def color(self):
        if self._selected == "checker":
            return None
        if self._selected == "custom":
            return self._custom_color
        for key, clr, _ in BG_PRESETS:
            if key == self._selected:
                return clr
        return None

    def _on_click(self, key):
        if key == "custom":
            init = self._custom_color or "#ffffff"
            result = colorchooser.askcolor(title="Background Color", initialcolor=init)
            if result and result[1]:
                self._custom_color = result[1]
                # repaint custom circle with chosen color
                c = self._circles["custom"]
                cx = cy = _CIRCLE_R + _PAD
                r = _CIRCLE_R
                c.delete("all")
                c.create_oval(cx - r, cy - r, cx + r, cy + r,
                              fill=self._custom_color, outline="#888", width=1, tags="ring")
            else:
                return  # cancelled

        self._selected = key
        self._highlight_selected()
        if self._on_change:
            self._on_change(self.color)

    def _highlight_selected(self):
        for key, canvas in self._circles.items():
            if key == self._selected:
                canvas.itemconfig("ring", outline="#00d4aa", width=2)
            else:
                canvas.itemconfig("ring", outline="#888", width=1)
