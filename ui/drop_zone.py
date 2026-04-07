import tkinter as tk
from ui.platform import FONT_FAMILY, HAS_DND
if HAS_DND:
    from tkinterdnd2 import DND_FILES


VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


class DropZone(tk.Canvas):
    """Drag-and-drop zone that accepts image files."""

    def __init__(self, parent, on_file_dropped, **kwargs):
        super().__init__(parent, **kwargs)
        self.on_file_dropped = on_file_dropped

        self.config(
            bg="#2a2a2a",
            highlightthickness=0,
            cursor="hand2",
        )

        self._draw_idle()
        self.bind("<Configure>", lambda e: self._draw_idle())
        self.bind("<Button-1>", self._on_click)

        # tkinterdnd2 bindings (graceful fallback: browse-only if unavailable)
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<DropEnter>>", self._on_drag_enter)
            self.dnd_bind("<<DropLeave>>", self._on_drag_leave)
            self.dnd_bind("<<Drop>>", self._on_drop)

    # -- drawing helpers --

    def _draw_idle(self):
        self._draw_border("#555555")
        self._draw_text()

    def _draw_border(self, color):
        self.delete("border")
        w = self.winfo_width() or 580
        h = self.winfo_height() or 140
        pad = 8
        self.create_rectangle(
            pad, pad, w - pad, h - pad,
            outline=color, width=2, dash=(8, 4), tags="border",
        )

    def _draw_text(self):
        self.delete("label")
        w = self.winfo_width() or 580
        h = self.winfo_height() or 140
        cx, cy = w // 2, h // 2
        if HAS_DND:
            title = "DROP IMAGE HERE"
            subtitle = "or click to browse  (JPG / PNG / WEBP / BMP)"
        else:
            title = "CLICK TO BROWSE"
            subtitle = "JPG / PNG / WEBP / BMP"
        self.create_text(
            cx, cy - 12,
            text=title,
            fill="#e0e0e0", font=(FONT_FAMILY, 14, "bold"), tags="label",
        )
        self.create_text(
            cx, cy + 14,
            text=subtitle,
            fill="#888888", font=(FONT_FAMILY, 9), tags="label",
        )

    # -- event handlers --

    def _on_drag_enter(self, event):
        self._draw_border("#00d4aa")
        return event.action

    def _on_drag_leave(self, event):
        self._draw_border("#555555")
        return event.action

    def _on_drop(self, event):
        self._draw_border("#555555")
        raw = event.data
        # tkinterdnd2 wraps paths with spaces in braces: {C:/path with space/file.png}
        if raw.startswith("{"):
            files = []
            i = 0
            while i < len(raw):
                if raw[i] == "{":
                    j = raw.index("}", i)
                    files.append(raw[i + 1 : j])
                    i = j + 1
                elif raw[i] == " ":
                    i += 1
                else:
                    end = raw.find(" ", i)
                    if end == -1:
                        end = len(raw)
                    files.append(raw[i:end])
                    i = end
        else:
            files = raw.split()

        if files:
            self.on_file_dropped(files[0])
        return event.action

    def _on_click(self, _event):
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="Select an image",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.webp *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.on_file_dropped(path)
