import tkinter as tk
import numpy as np
from PIL import Image, ImageTk

from ui.bg_combo import BgCombo

_CHECKER_SIZE = 10


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


class ResultPanel(tk.Frame):
    """Before / After preview with shared zoom/pan and background selector."""

    def __init__(self, parent, on_edit=None, **kwargs):
        super().__init__(parent, bg="#1e1e1e", **kwargs)
        self._result_image = None
        self._before_image = None
        self._original_stem = ""
        self._on_edit_cb = on_edit
        self._spinner_angle = 0
        self._spinner_running = False
        self._resize_timer = None
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
        self._cached_zoom = None

        # -- save row (BOTTOM) --
        save_frame = tk.Frame(self, bg="#1e1e1e")
        save_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))

        tk.Label(save_frame, text="Save as:", bg="#1e1e1e", fg="#e0e0e0",
                 font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(0, 6))
        self._format_var = tk.StringVar(value="png")
        for fmt, label in [("png", "PNG"), ("webp", "WebP")]:
            tk.Radiobutton(
                save_frame, text=label, variable=self._format_var, value=fmt,
                bg="#1e1e1e", fg="#e0e0e0", selectcolor="#2a2a2a",
                activebackground="#1e1e1e", activeforeground="#00d4aa",
                font=("Segoe UI", 10),
            ).pack(side=tk.LEFT, padx=3)

        # buttons right-aligned, same width
        self._edit_btn = tk.Button(
            save_frame, text="Edit", command=self._on_edit, width=10,
            bg="#3a3a3a", fg="#00d4aa", activebackground="#4a4a4a",
            activeforeground="#00d4aa",
            font=("Segoe UI", 10, "bold"), relief=tk.FLAT, pady=3,
            cursor="hand2", state=tk.DISABLED,
        )
        self._edit_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self._save_btn = tk.Button(
            save_frame, text="Save File", command=self._on_save, width=10,
            bg="#00d4aa", fg="#1e1e1e", activebackground="#00b894",
            font=("Segoe UI", 10, "bold"), relief=tk.FLAT, pady=3,
            cursor="hand2", state=tk.DISABLED,
        )
        self._save_btn.pack(side=tk.RIGHT, padx=(0, 0))

        # -- header: Before | After | BG circles --
        header = tk.Frame(self, bg="#1e1e1e")
        header.pack(fill=tk.X, pady=(0, 2))
        header.columnconfigure(0, weight=1, uniform="hdr")
        header.columnconfigure(1, weight=1, uniform="hdr")
        header.columnconfigure(2, weight=0)

        tk.Label(header, text="Before", bg="#1e1e1e", fg="#888888",
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky=tk.W)
        tk.Label(header, text="After", bg="#1e1e1e", fg="#888888",
                 font=("Segoe UI", 9)).grid(row=0, column=1, sticky=tk.W)

        bg_frame = tk.Frame(header, bg="#1e1e1e")
        bg_frame.grid(row=0, column=2, sticky=tk.E)
        tk.Label(bg_frame, text="BG", bg="#1e1e1e", fg="#666666",
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 2))
        self._bg_combo = BgCombo(bg_frame, on_change=self._on_bg_change, bg="#1e1e1e")
        self._bg_combo.pack(side=tk.LEFT)

        # -- canvases: grid uniform 50:50 --
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

    # ===== background =====

    def _on_bg_change(self, color):
        self._bg_color = color
        self._invalidate_cache()
        self._rerender_zoom()

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

        if abs(self._zoom - (self._cached_zoom or 1.0)) / max(self._cached_zoom or 1.0, 0.01) > 0.25:
            self._rerender_zoom()
        else:
            self._update_pan_positions()

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
            self._rerender_zoom()

    def _on_reset_zoom(self, _event):
        self._zoom = 1.0
        self._pan_x = self._pan_y = 0
        self._rerender_zoom()

    def _update_pan_positions(self):
        if self._before_img_id and self._before_image:
            cw, ch = self._before_canvas.winfo_width(), self._before_canvas.winfo_height()
            self._before_canvas.coords(self._before_img_id, cw // 2 + self._pan_x, ch // 2 + self._pan_y)
        if self._after_img_id and self._result_image and not self._spinner_running:
            cw, ch = self._after_canvas.winfo_width(), self._after_canvas.winfo_height()
            self._after_canvas.coords(self._after_img_id, cw // 2 + self._pan_x, ch // 2 + self._pan_y)

    def _invalidate_cache(self):
        self._cached_zoom = None

    def _rerender_zoom(self):
        self._resize_timer = None
        if self._before_image:
            self._render_before()
        if self._result_image and not self._spinner_running:
            self._render_after()
        self._cached_zoom = self._zoom

    def _on_canvas_resize(self, _event=None):
        if self._resize_timer:
            self.after_cancel(self._resize_timer)
        self._resize_timer = self.after(60, self._rerender_zoom)

    # ===== rendering =====

    def _composite(self, display):
        dw, dh = display.size
        bg_c = self._bg_color
        bg = _make_checker(dw, dh) if bg_c is None else Image.new("RGB", (dw, dh), _hex_to_rgb(bg_c))
        if display.mode == "RGBA":
            bg.paste(display, mask=display.split()[3])
        else:
            bg.paste(display)
        return bg

    def _canvas_bg(self):
        return self._bg_color if self._bg_color else "#2a2a2a"

    def _render_before(self):
        cw, ch = self._before_canvas.winfo_width(), self._before_canvas.winfo_height()
        if cw < 20 or ch < 20:
            return
        iw, ih = self._before_image.size
        scale = min((cw - 4) / iw, (ch - 4) / ih) * self._zoom
        dw, dh = max(1, int(iw * scale)), max(1, int(ih * scale))
        display = self._before_image.resize((dw, dh), Image.LANCZOS)
        final = self._composite(display)
        self._before_canvas.config(bg=self._canvas_bg())
        self._before_photo = ImageTk.PhotoImage(final)
        self._before_canvas.delete("all")
        self._before_img_id = self._before_canvas.create_image(
            cw // 2 + self._pan_x, ch // 2 + self._pan_y, image=self._before_photo)

    def _render_after(self):
        cw, ch = self._after_canvas.winfo_width(), self._after_canvas.winfo_height()
        if cw < 20 or ch < 20:
            return
        iw, ih = self._result_image.size
        scale = min((cw - 4) / iw, (ch - 4) / ih) * self._zoom
        dw, dh = max(1, int(iw * scale)), max(1, int(ih * scale))
        display = self._result_image.resize((dw, dh), Image.LANCZOS)
        final = self._composite(display)
        self._after_canvas.config(bg=self._canvas_bg())
        self._after_photo = ImageTk.PhotoImage(final)
        self._after_canvas.delete("all")
        self._after_img_id = self._after_canvas.create_image(
            cw // 2 + self._pan_x, ch // 2 + self._pan_y, image=self._after_photo)

    # ===== public =====

    def show_before(self, pil_image):
        self._before_image = pil_image
        self._zoom = 1.0
        self._pan_x = self._pan_y = 0
        self._invalidate_cache()
        self._render_before()

    def show_after(self, pil_image):
        self._result_image = pil_image
        self._render_after()
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
        if fmt == "webp":
            self._result_image.save(path, format="WEBP", lossless=True)
        else:
            self._result_image.save(path, format="PNG")
