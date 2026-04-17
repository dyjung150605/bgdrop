import tkinter as tk
from tkinter import ttk
import numpy as np
from PIL import Image, ImageTk

from ui.bg_combo import BgCombo
import ui.platform as platform
from ui.platform import FONT_FAMILY

_CHECKER_SIZE = 10
# pre-render cache at this max dimension for fast zoom
_CACHE_MAX = 1200


def _make_checker(width, height):
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    y_idx = np.arange(height)[:, None] // _CHECKER_SIZE
    x_idx = np.arange(width)[None, :] // _CHECKER_SIZE
    mask = (x_idx + y_idx) % 2 == 0
    arr[mask] = [200, 200, 200]
    arr[~mask] = [255, 255, 255]
    return Image.fromarray(arr)


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _composite(display, bg_color):
    dw, dh = display.size
    bg = _make_checker(dw, dh) if bg_color is None else Image.new("RGB", (dw, dh), _hex_to_rgb(bg_color))
    if display.mode == "RGBA":
        bg.paste(display, mask=display.split()[3])
    else:
        bg.paste(display)
    return bg


class ResultPanel(tk.Frame):
    """Before / After preview with shared zoom/pan and background selector."""

    def __init__(self, parent, on_edit=None, on_file_dropped=None, **kwargs):
        super().__init__(parent, bg="#1e1e1e", **kwargs)
        self._result_image = None
        self._before_image = None
        self._original_stem = ""
        self._on_edit_cb = on_edit
        self._on_file_dropped = on_file_dropped
        self._spinner_angle = 0
        self._spinner_running = False
        self._resize_timer = None
        self._sharp_timer = None
        self._bg_color = None

        # zoom / pan
        self._zoom = 1.0
        self._pan_x = 0
        self._pan_y = 0
        self._drag_pan = None
        self._before_img_id = None
        self._after_img_id = None
        self._before_photo = None
        self._after_photo = None

        # pre-composited caches (at _CACHE_MAX size) for fast zoom
        self._before_cache = None  # PIL RGB
        self._after_cache = None   # PIL RGB

        # -- save row (BOTTOM) --
        save_frame = tk.Frame(self, bg="#1e1e1e")
        save_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))

        tk.Label(save_frame, text="Save as:", bg="#1e1e1e", fg="#e0e0e0",
                 font=(FONT_FAMILY, 10)).pack(side=tk.LEFT, padx=(0, 6))
        self._format_var = tk.StringVar(value="png")
        for fmt, label in [("png", "PNG"), ("webp", "WebP")]:
            tk.Radiobutton(
                save_frame, text=label, variable=self._format_var, value=fmt,
                bg="#1e1e1e", fg="#e0e0e0", selectcolor="#2a2a2a",
                activebackground="#1e1e1e", activeforeground="#00d4aa",
                font=(FONT_FAMILY, 10),
            ).pack(side=tk.LEFT, padx=3)

        self._edit_btn = tk.Button(
            save_frame, text="Edit", command=self._on_edit, width=10,
            bg="#3a3a3a", fg="#00d4aa", activebackground="#4a4a4a",
            activeforeground="#00d4aa",
            font=(FONT_FAMILY, 10, "bold"), relief=tk.FLAT, pady=3,
            cursor="hand2", state=tk.DISABLED,
        )
        self._edit_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self._save_btn = tk.Button(
            save_frame, text="Save", command=self._on_save, width=10,
            bg="#00d4aa", fg="#1e1e1e", activebackground="#00b894",
            font=(FONT_FAMILY, 10, "bold"), relief=tk.FLAT, pady=3,
            cursor="hand2", state=tk.DISABLED,
        )
        self._save_btn.pack(side=tk.RIGHT)

        # -- header --
        header = tk.Frame(self, bg="#1e1e1e")
        header.pack(fill=tk.X, pady=(0, 2))
        header.columnconfigure(0, weight=1, uniform="hdr")
        header.columnconfigure(1, weight=1, uniform="hdr")
        header.columnconfigure(2, weight=0)

        tk.Label(header, text="Before", bg="#1e1e1e", fg="#888888",
                 font=(FONT_FAMILY, 9)).grid(row=0, column=0, sticky=tk.W)
        tk.Label(header, text="After", bg="#1e1e1e", fg="#888888",
                 font=(FONT_FAMILY, 9)).grid(row=0, column=1, sticky=tk.W, padx=(4, 0))

        bg_frame = tk.Frame(header, bg="#1e1e1e")
        bg_frame.grid(row=0, column=2, sticky=tk.E)
        tk.Label(bg_frame, text="BG", bg="#1e1e1e", fg="#666666",
                 font=(FONT_FAMILY, 8)).pack(side=tk.LEFT, padx=(0, 2))
        self._bg_combo = BgCombo(bg_frame, on_change=self._on_bg_change, bg="#1e1e1e")
        self._bg_combo.pack(side=tk.LEFT)

        # -- canvases --
        canvas_frame = tk.Frame(self, bg="#1e1e1e")
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        canvas_frame.columnconfigure(0, weight=1, uniform="cv")
        canvas_frame.columnconfigure(1, weight=1, uniform="cv")
        canvas_frame.rowconfigure(0, weight=1)

        self._before_canvas = tk.Canvas(
            canvas_frame, bg="#2a2a2a", highlightthickness=1,
            highlightbackground="#444444", cursor="hand2",
        )
        self._before_canvas.grid(row=0, column=0, sticky="nsew", padx=(0, 2))

        self._after_canvas = tk.Canvas(
            canvas_frame, bg="#2a2a2a", highlightthickness=1,
            highlightbackground="#444444", cursor="hand2",
        )
        self._after_canvas.grid(row=0, column=1, sticky="nsew", padx=(2, 0))

        for canvas in [self._before_canvas, self._after_canvas]:
            canvas.bind("<Configure>", self._on_canvas_resize)
            canvas.bind("<MouseWheel>", self._on_wheel)
            canvas.bind("<ButtonPress-1>", self._on_pan_start)
            canvas.bind("<B1-Motion>", self._on_pan_drag)
            canvas.bind("<ButtonRelease-1>", self._on_pan_end)
            canvas.bind("<Double-Button-1>", self._on_reset_zoom)
            canvas.bind("<Enter>", lambda e: e.widget.focus_set())

        # -- zoom slider --
        self._zoom_scale_updating = False
        self._zoom_render_timer = None

        zoom_frame = tk.Frame(canvas_frame, bg="#1e1e1e")
        zoom_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        tk.Label(zoom_frame, text="\u2212", bg="#1e1e1e", fg="#888888",
                 font=(FONT_FAMILY, 12)).pack(side=tk.LEFT, padx=(4, 0))

        self._zoom_scale = ttk.Scale(
            zoom_frame, from_=30, to=200, orient=tk.HORIZONTAL,
            command=self._on_zoom_scale,
        )
        self._zoom_scale.set(100)
        self._zoom_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self._zoom_scale.bind("<Double-Button-1>", self._on_reset_zoom)

        tk.Label(zoom_frame, text="+", bg="#1e1e1e", fg="#888888",
                 font=(FONT_FAMILY, 12)).pack(side=tk.LEFT)

        self._zoom_label = tk.Label(zoom_frame, text="100%", bg="#1e1e1e",
                                     fg="#888888", font=(FONT_FAMILY, 8), width=5)
        self._zoom_label.pack(side=tk.LEFT, padx=(4, 4))

        tk.Label(zoom_frame, text="drag \u2192 pan  |  double-click \u2192 reset",
                 bg="#1e1e1e", fg="#555555", font=(FONT_FAMILY, 8)
                 ).pack(side=tk.RIGHT, padx=(0, 8))

        self._setup_drop()

    # ===== drop =====

    def _setup_drop(self):
        if not platform.HAS_DND:
            return
        try:
            from tkinterdnd2 import DND_FILES
            for canvas in [self._before_canvas, self._after_canvas]:
                canvas.drop_target_register(DND_FILES)
                canvas.dnd_bind("<<Drop>>", self._on_canvas_drop)
        except Exception:
            platform.HAS_DND = False

    def _on_canvas_drop(self, event):
        if self._on_file_dropped is None:
            return event.action
        raw = event.data
        if raw.startswith("{"):
            end = raw.index("}")
            path = raw[1:end]
        else:
            path = raw.split()[0] if raw else ""
        if path:
            self._on_file_dropped(path)
        return event.action

    # ===== background =====

    def _on_bg_change(self, color):
        self._bg_color = color
        self._rebuild_before_cache()
        self._rebuild_after_cache()
        self._render_fast()
        listener = getattr(self, "_bg_listener", None)
        if listener:
            listener(color)

    def set_bg_listener(self, callback):
        """Register a callback invoked with (color) whenever BG changes."""
        self._bg_listener = callback

    def get_bg_color(self):
        return self._bg_color

    # ===== caching =====

    def _rebuild_before_cache(self):
        if self._before_image:
            t = self._before_image.copy()
            t.thumbnail((_CACHE_MAX, _CACHE_MAX), Image.LANCZOS)
            self._before_cache = _composite(t, self._bg_color)

    def _rebuild_after_cache(self):
        if self._result_image:
            t = self._result_image.copy()
            t.thumbnail((_CACHE_MAX, _CACHE_MAX), Image.LANCZOS)
            self._after_cache = _composite(t, self._bg_color)

    # ===== zoom / pan =====

    def _on_wheel(self, event):
        if not self._before_image and not self._result_image:
            return
        canvas = event.widget
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        mx, my = event.x - cw // 2, event.y - ch // 2

        old_zoom = self._zoom
        factor = 1.15
        self._zoom = min(self._zoom * factor, 10.0) if event.delta > 0 \
            else max(self._zoom / factor, 0.5)

        ratio = self._zoom / old_zoom
        self._pan_x = int(mx - (mx - self._pan_x) * ratio)
        self._pan_y = int(my - (my - self._pan_y) * ratio)

        # fast render from cache, schedule sharp render
        self._sync_zoom_slider()
        self._render_fast()
        self._schedule_sharp()

    def _on_pan_start(self, event):
        self._drag_pan = (event.x, event.y, self._pan_x, self._pan_y)

    def _on_pan_drag(self, event):
        if self._drag_pan:
            sx, sy, px, py = self._drag_pan
            self._pan_x = px + (event.x - sx)
            self._pan_y = py + (event.y - sy)
            self._update_pan_positions()

    def _on_pan_end(self, _event):
        if self._drag_pan:
            self._drag_pan = None
            self._schedule_sharp()

    def _on_zoom_scale(self, val):
        if self._zoom_scale_updating:
            return
        if not self._before_image and not self._result_image:
            return
        self._zoom = float(val) / 100.0
        if hasattr(self, '_zoom_label'):
            self._zoom_label.config(text=f"{int(float(val))}%")
        self._render_fast()
        # debounce sharp render while dragging
        if self._zoom_render_timer:
            self.after_cancel(self._zoom_render_timer)
        self._zoom_render_timer = self.after(200, self._render_sharp)

    def _sync_zoom_slider(self):
        self._zoom_scale_updating = True
        pct = int(self._zoom * 100)
        self._zoom_scale.set(pct)
        self._zoom_label.config(text=f"{pct}%")
        self._zoom_scale_updating = False

    def _on_reset_zoom(self, _event):
        self._zoom = 1.0
        self._pan_x = self._pan_y = 0
        self._sync_zoom_slider()
        self._render_sharp()

    def _update_pan_positions(self):
        if self._before_img_id and self._before_image:
            cw, ch = self._before_canvas.winfo_width(), self._before_canvas.winfo_height()
            self._before_canvas.coords(self._before_img_id, cw // 2 + self._pan_x, ch // 2 + self._pan_y)
        if self._after_img_id and self._result_image and not self._spinner_running:
            cw, ch = self._after_canvas.winfo_width(), self._after_canvas.winfo_height()
            self._after_canvas.coords(self._after_img_id, cw // 2 + self._pan_x, ch // 2 + self._pan_y)

    def _schedule_sharp(self):
        if self._sharp_timer:
            self.after_cancel(self._sharp_timer)
        self._sharp_timer = self.after(200, self._render_sharp)

    def _on_canvas_resize(self, _event=None):
        if self._resize_timer:
            self.after_cancel(self._resize_timer)
        self._resize_timer = self.after(80, self._render_sharp)

    # ===== rendering =====

    def _canvas_bg(self):
        return self._bg_color if self._bg_color else "#2a2a2a"

    def _render_one(self, canvas, source, cache):
        """Render from cache (fast) or source (sharp) onto canvas."""
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw < 20 or ch < 20 or source is None:
            return None, None
        iw, ih = source.size
        scale = min((cw - 4) / iw, (ch - 4) / ih) * self._zoom
        dw, dh = max(1, int(iw * scale)), max(1, int(ih * scale))

        if cache is not None:
            img = cache.resize((dw, dh), Image.BILINEAR)
        else:
            display = source.resize((dw, dh), Image.LANCZOS)
            img = _composite(display, self._bg_color)

        canvas.config(bg=self._canvas_bg())
        photo = ImageTk.PhotoImage(img)
        canvas.delete("all")
        img_id = canvas.create_image(
            cw // 2 + self._pan_x, ch // 2 + self._pan_y, image=photo)
        return photo, img_id

    def _render_fast(self):
        """Quick render from pre-composited caches."""
        if self._before_image:
            self._before_photo, self._before_img_id = self._render_one(
                self._before_canvas, self._before_image, self._before_cache)
        if self._result_image and not self._spinner_running:
            self._after_photo, self._after_img_id = self._render_one(
                self._after_canvas, self._result_image, self._after_cache)

    def _render_sharp(self):
        """Full quality render from original images."""
        self._sharp_timer = None
        self._resize_timer = None
        if self._before_image:
            self._before_photo, self._before_img_id = self._render_one(
                self._before_canvas, self._before_image, None)
        if self._result_image and not self._spinner_running:
            self._after_photo, self._after_img_id = self._render_one(
                self._after_canvas, self._result_image, None)

    # ===== public =====

    def show_before(self, pil_image):
        self._before_image = pil_image
        self._zoom = 1.0
        self._pan_x = self._pan_y = 0
        self._sync_zoom_slider()
        self._rebuild_before_cache()
        self._before_photo, self._before_img_id = self._render_one(
            self._before_canvas, self._before_image, None)

    def show_after(self, pil_image):
        self._result_image = pil_image
        self._rebuild_after_cache()
        self._after_photo, self._after_img_id = self._render_one(
            self._after_canvas, self._result_image, None)
        self._save_btn.config(state=tk.NORMAL)
        self._edit_btn.config(state=tk.NORMAL)
        self.stop_spinner()

    def start_spinner(self):
        self._spinner_running = True
        self._spinner_angle = 0
        self._after_canvas.delete("all")
        self._after_img_id = None
        self._save_btn.config(state=tk.DISABLED)
        self._edit_btn.config(state=tk.DISABLED)
        self._animate_spinner()

    def stop_spinner(self):
        self._spinner_running = False

    def set_original_stem(self, stem):
        self._original_stem = stem

    def clear(self):
        for c in [self._before_canvas, self._after_canvas]:
            c.delete("all")
        self._result_image = self._before_image = None
        self._before_img_id = self._after_img_id = None
        self._before_photo = self._after_photo = None
        self._before_cache = self._after_cache = None
        self._save_btn.config(state=tk.DISABLED)
        self._edit_btn.config(state=tk.DISABLED)
        self.stop_spinner()

    def _animate_spinner(self):
        if not self._spinner_running:
            return
        cw, ch = self._after_canvas.winfo_width(), self._after_canvas.winfo_height()
        cx, cy = max(cw // 2, 1), max(ch // 2, 1)
        r = 24
        self._after_canvas.delete("spinner")
        self._after_canvas.create_arc(
            cx - r, cy - r, cx + r, cy + r,
            start=self._spinner_angle, extent=90, style=tk.ARC,
            outline="#00d4aa", width=3, tags="spinner")
        self._spinner_angle = (self._spinner_angle + 15) % 360
        self._after_canvas.after(50, self._animate_spinner)

    def _on_edit(self):
        if self._result_image and self._on_edit_cb:
            self._on_edit_cb(self._result_image, self._format_var.get(), self._original_stem)

    def _prepare_save_image(self, source):
        """Composite on selected background if any, otherwise save as-is (transparent)."""
        if self._bg_color is None:
            return source  # checker = transparent, save RGBA as-is
        return _composite(source, self._bg_color)

    def _on_save(self):
        if self._result_image is None:
            return
        from tkinter import filedialog
        fmt = self._format_var.get()
        ext = f".{fmt}"
        default_name = f"{self._original_stem}_nobg{ext}" if self._original_stem else f"output{ext}"
        path = filedialog.asksaveasfilename(
            title="Save image", defaultextension=ext, initialfile=default_name,
            filetypes=[(f"{fmt.upper()} files", f"*{ext}"), ("All files", "*.*")])
        if not path:
            return
        save_img = self._prepare_save_image(self._result_image)
        if fmt == "webp":
            save_img.save(path, format="WEBP", lossless=True)
        else:
            save_img.save(path, format="PNG")
