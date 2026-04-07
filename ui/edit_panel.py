import tkinter as tk
import numpy as np
from PIL import Image, ImageTk

from ui.bg_combo import BgCombo
from ui.platform import FONT_FAMILY

_CHECKER_SIZE = 10
_MOSAIC_BLOCK = 10
_BRUSH_MIN = 5
_BRUSH_MAX = 60
_BRUSH_DEFAULT = 54


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
    if bg_color is None:
        return display
    bg = Image.new("RGB", (dw, dh), _hex_to_rgb(bg_color))
    if display.mode == "RGBA":
        bg.paste(display, mask=display.split()[3])
    else:
        bg.paste(display)
    return bg


def _complementary_hex(r, g, b):
    """Return hex color complementary to (r,g,b)."""
    cr, cg, cb = 255 - r, 255 - g, 255 - b
    # if too close to mid-grey, push toward white
    if abs(cr - 128) < 30 and abs(cg - 128) < 30 and abs(cb - 128) < 30:
        return "#ffffff"
    return f"#{cr:02x}{cg:02x}{cb:02x}"


class EditPanel(tk.Frame):
    """Edit view: crop + mosaic brush with background selector."""

    def __init__(self, parent, on_save, on_cancel, **kwargs):
        super().__init__(parent, bg="#1e1e1e", **kwargs)
        self._on_save_cb = on_save
        self._on_cancel_cb = on_cancel

        self._original = None
        self._working = None
        self._display_photo = None
        self._display_pil = None  # cached display-size PIL for pixel picking
        self._scale = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self._bg_color = None  # None=checker

        self._tool = None
        self._history = []
        self._original_stem = ""
        self._resize_timer = None
        self._refresh_scheduled = False

        # zoom / pan
        self._edit_zoom = 1.0
        self._edit_pan_x = 0
        self._edit_pan_y = 0
        self._pan_drag = None

        # mosaic
        self._mosaic_radius = _BRUSH_DEFAULT
        self._mosaic_painting = False

        # crop
        self._crop_phase = None
        self._crop_image_rect = None
        self._drag_start = None
        self._crop_move_start = None
        self._rect_id = None

        # -- toolbar --
        toolbar = tk.Frame(self, bg="#1e1e1e")
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(4, 4), padx=8)

        tk.Label(toolbar, text="Tools:", bg="#1e1e1e", fg="#888888",
                 font=(FONT_FAMILY, 9)).pack(side=tk.LEFT, padx=(0, 6))

        self._crop_btn = tk.Button(
            toolbar, text="Crop", command=lambda: self._select_tool("crop"),
            bg="#2a2a2a", fg="#e0e0e0", activebackground="#00d4aa",
            font=(FONT_FAMILY, 9, "bold"), relief=tk.FLAT, padx=12, pady=2,
            cursor="hand2",
        )
        self._crop_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._mosaic_btn = tk.Button(
            toolbar, text="Mosaic", command=lambda: self._select_tool("mosaic"),
            bg="#2a2a2a", fg="#e0e0e0", activebackground="#00d4aa",
            font=(FONT_FAMILY, 9, "bold"), relief=tk.FLAT, padx=12, pady=2,
            cursor="hand2",
        )
        self._mosaic_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._reset_btn = tk.Button(
            toolbar, text="Reset", command=self._reset,
            bg="#2a2a2a", fg="#e0e0e0", activebackground="#ffaa00",
            font=(FONT_FAMILY, 9), relief=tk.FLAT, padx=10, pady=2,
            cursor="hand2",
        )
        self._reset_btn.pack(side=tk.LEFT, padx=(8, 0))

        # BG combo (right side of toolbar)
        self._bg_combo = BgCombo(toolbar, on_change=self._on_bg_change, bg="#1e1e1e")
        self._bg_combo.pack(side=tk.RIGHT, padx=(4, 0))
        tk.Label(toolbar, text="BG", bg="#1e1e1e", fg="#888888",
                 font=(FONT_FAMILY, 8)).pack(side=tk.RIGHT)

        self._hint_var = tk.StringVar(value="Select a tool")
        tk.Label(toolbar, textvariable=self._hint_var, bg="#1e1e1e", fg="#666666",
                 font=(FONT_FAMILY, 8)).pack(side=tk.RIGHT, padx=(0, 12))

        # -- bottom buttons --
        btn_frame = tk.Frame(self, bg="#1e1e1e")
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 4), padx=8)

        self._format_var = tk.StringVar(value="png")
        for fmt, label in [("png", "PNG"), ("webp", "WebP")]:
            tk.Radiobutton(
                btn_frame, text=label, variable=self._format_var, value=fmt,
                bg="#1e1e1e", fg="#e0e0e0", selectcolor="#2a2a2a",
                activebackground="#1e1e1e", activeforeground="#00d4aa",
                font=(FONT_FAMILY, 9),
            ).pack(side=tk.LEFT, padx=4)

        tk.Button(
            btn_frame, text="Cancel", command=self._do_cancel, width=10,
            bg="#3a3a3a", fg="#e0e0e0", activebackground="#4a4a4a",
            font=(FONT_FAMILY, 10, "bold"), relief=tk.FLAT, pady=3,
            cursor="hand2",
        ).pack(side=tk.RIGHT, padx=(4, 0))
        tk.Button(
            btn_frame, text="Save", command=self._do_save, width=10,
            bg="#00d4aa", fg="#1e1e1e", activebackground="#00b894",
            font=(FONT_FAMILY, 10, "bold"), relief=tk.FLAT, pady=3,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        # -- canvas --
        self._canvas = tk.Canvas(
            self, bg="#2a2a2a", highlightthickness=1,
            highlightbackground="#444444", cursor="crosshair",
        )
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=8)
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Double-Button-1>", self._on_double_click)
        self._canvas.bind("<Motion>", self._on_motion)
        self._canvas.bind("<MouseWheel>", self._on_wheel)
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self._canvas.bind("<Key-Escape>", self._on_key_escape)
        self._canvas.bind("<Key-Return>", self._on_key_return)
        # Ctrl key visual feedback
        self._canvas.bind("<KeyPress-Control_L>", lambda e: self._canvas.config(cursor="fleur"))
        self._canvas.bind("<KeyRelease-Control_L>", lambda e: self._restore_cursor())
        self._canvas.bind("<KeyPress-Control_R>", lambda e: self._canvas.config(cursor="fleur"))
        self._canvas.bind("<KeyRelease-Control_R>", lambda e: self._restore_cursor())
        # zoom/pan: Ctrl+wheel = zoom, Ctrl+drag or middle-drag = pan
        self._canvas.bind("<Control-MouseWheel>", self._on_zoom_wheel)
        self._canvas.bind("<Control-ButtonPress-1>", self._on_pan_start)
        self._canvas.bind("<Control-B1-Motion>", self._on_pan_drag)
        self._canvas.bind("<Control-ButtonRelease-1>", self._on_pan_end)
        self._canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self._canvas.bind("<B2-Motion>", self._on_pan_drag)
        self._canvas.bind("<ButtonRelease-2>", self._on_pan_end)

    # -- public --

    def load_image(self, pil_image: Image.Image, format_val="png", stem=""):
        self._original = pil_image.copy()
        self._working = pil_image.copy()
        self._history = []
        self._crop_phase = None
        self._crop_image_rect = None
        self._mosaic_radius = _BRUSH_DEFAULT
        self._edit_zoom = 1.0
        self._edit_pan_x = 0
        self._edit_pan_y = 0
        self._original_stem = stem
        self._format_var.set(format_val)
        self._canvas.focus_set()
        self.after(50, self._after_load)

    def _after_load(self):
        self._refresh_canvas()
        self._select_tool("crop")

    # -- bg change --

    def _on_bg_change(self, color):
        self._bg_color = color
        self._refresh_canvas()

    # -- resize --

    def _on_canvas_resize(self, event=None):
        if self._resize_timer:
            self.after_cancel(self._resize_timer)
        self._resize_timer = self.after(80, self._refresh_canvas)

    def _restore_cursor(self):
        if self._tool == "crop":
            cursor = "fleur" if self._crop_phase == "placed" else "crosshair"
        elif self._tool == "mosaic":
            cursor = "none"
        else:
            cursor = "crosshair"
        self._canvas.config(cursor=cursor)

    # -- zoom / pan --

    def _on_zoom_wheel(self, event):
        factor = 1.15
        self._edit_zoom = min(self._edit_zoom * factor, 10.0) if event.delta > 0 \
            else max(self._edit_zoom / factor, 0.3)
        # zoom from center — no pan adjustment, no drift
        self._refresh_canvas()

    def _on_pan_drag(self, event):
        if self._pan_drag:
            sx, sy, px, py = self._pan_drag
            self._edit_pan_x = px + (event.x - sx)
            self._edit_pan_y = py + (event.y - sy)
            # move canvas items directly — no re-render, no flicker
            self._canvas.delete("cursor")
            items = self._canvas.find_all()
            dx = event.x - self._last_pan_x if hasattr(self, '_last_pan_x') else 0
            dy = event.y - self._last_pan_y if hasattr(self, '_last_pan_y') else 0
            for item in items:
                self._canvas.move(item, dx, dy)
            self._last_pan_x = event.x
            self._last_pan_y = event.y

    def _on_pan_start(self, event):
        self._pan_drag = (event.x, event.y, self._edit_pan_x, self._edit_pan_y)
        self._last_pan_x = event.x
        self._last_pan_y = event.y

    def _on_pan_end(self, _event):
        self._pan_drag = None
        self._refresh_canvas()  # sharp re-render at final position

    def _on_zoom_reset(self, _event):
        self._edit_zoom = 1.0
        self._edit_pan_x = self._edit_pan_y = 0
        self._refresh_canvas()

    # -- tool selection --

    def _select_tool(self, tool):
        if self._crop_phase == "placed":
            self._cancel_crop()
        self._tool = tool
        self._crop_phase = None
        self._update_buttons()
        self._canvas.focus_set()
        if tool == "crop":
            self._canvas.config(cursor="crosshair")
            self._hint_var.set("Drag to crop  (Shift \u2192 square)")
        elif tool == "mosaic":
            self._canvas.config(cursor="none")
            self._hint_var.set(f"Brush {self._mosaic_radius}  (wheel to resize)")

    def _update_buttons(self):
        for btn, name in [(self._crop_btn, "crop"), (self._mosaic_btn, "mosaic")]:
            if self._tool == name:
                btn.config(bg="#00d4aa", fg="#1e1e1e")
            else:
                btn.config(bg="#2a2a2a", fg="#e0e0e0")

    # -- coords --

    def _canvas_to_image(self, cx, cy):
        ix = int((cx - self._offset_x) / self._scale)
        iy = int((cy - self._offset_y) / self._scale)
        if self._working is None:
            return 0, 0
        iw, ih = self._working.size
        return max(0, min(ix, iw)), max(0, min(iy, ih))

    def _image_to_canvas(self, ix, iy):
        return ix * self._scale + self._offset_x, iy * self._scale + self._offset_y

    # -- canvas display --

    def _composite(self, display):
        dw, dh = display.size
        if self._bg_color is None:
            bg = _make_checker(dw, dh)
        else:
            bg = Image.new("RGB", (dw, dh), _hex_to_rgb(self._bg_color))
        if display.mode == "RGBA":
            bg.paste(display, mask=display.split()[3])
        else:
            bg.paste(display)
        return bg

    def _refresh_canvas(self):
        self._resize_timer = None
        self._refresh_scheduled = False
        if self._working is None:
            return
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw < 20 or ch < 20:
            return
        iw, ih = self._working.size

        base_scale = min((cw - 8) / iw, (ch - 8) / ih, 1.0)
        self._scale = base_scale * self._edit_zoom
        dw = int(iw * self._scale)
        dh = int(ih * self._scale)
        self._offset_x = (cw - dw) // 2 + self._edit_pan_x
        self._offset_y = (ch - dh) // 2 + self._edit_pan_y

        display = self._working.resize((dw, dh), Image.LANCZOS)
        self._display_pil = display  # cache for pixel picking

        final = self._composite(display)
        bg_hex = self._bg_color if self._bg_color else "#2a2a2a"
        self._canvas.config(bg=bg_hex)

        self._display_photo = ImageTk.PhotoImage(final)
        self._canvas.delete("all")
        self._canvas.create_image(
            self._offset_x, self._offset_y,
            anchor=tk.NW, image=self._display_photo,
        )
        self._redraw_crop_rect()

    def _redraw_crop_rect(self):
        if self._crop_phase in ("placed", "moving") and self._crop_image_rect:
            ix1, iy1, ix2, iy2 = self._crop_image_rect
            cx1, cy1 = self._image_to_canvas(ix1, iy1)
            cx2, cy2 = self._image_to_canvas(ix2, iy2)
            self._rect_id = self._canvas.create_rectangle(
                cx1, cy1, cx2, cy2, outline="#00d4aa", width=2,
            )

    # -- mosaic cursor: complementary-color solid circle --

    def _get_pixel_color_at(self, cx, cy):
        """Get the RGB of the display image pixel under canvas coords."""
        if self._display_pil is None:
            return (128, 128, 128)
        px = int(cx - self._offset_x)
        py = int(cy - self._offset_y)
        dw, dh = self._display_pil.size
        if 0 <= px < dw and 0 <= py < dh:
            pix = self._display_pil.getpixel((px, py))
            return pix[:3]
        return (128, 128, 128)

    def _on_motion(self, event):
        self._canvas.delete("cursor")
        if self._tool == "mosaic" and self._working and not self._mosaic_painting:
            r = self._mosaic_radius * self._scale
            rgb = self._get_pixel_color_at(event.x, event.y)
            color = _complementary_hex(*rgb)
            self._canvas.create_oval(
                event.x - r, event.y - r, event.x + r, event.y + r,
                outline=color, width=1.5, tags="cursor",
            )

    def _on_wheel(self, event):
        if self._tool == "mosaic":
            delta = 3 if event.delta > 0 else -3
            self._mosaic_radius = max(_BRUSH_MIN, min(_BRUSH_MAX, self._mosaic_radius + delta))
            self._hint_var.set(f"Brush {self._mosaic_radius}  (wheel to resize)")
            self._canvas.delete("cursor")
            r = self._mosaic_radius * self._scale
            rgb = self._get_pixel_color_at(event.x, event.y)
            color = _complementary_hex(*rgb)
            self._canvas.create_oval(
                event.x - r, event.y - r, event.x + r, event.y + r,
                outline=color, width=1.5, tags="cursor",
            )

    # ==================== MOUSE ====================

    def _on_press(self, event):
        if event.state & 0x4:  # Ctrl held — pan mode, skip tool
            return
        if self._tool is None or self._working is None:
            return
        self._canvas.focus_set()
        if self._tool == "crop":
            self._crop_on_press(event)
        elif self._tool == "mosaic":
            self._mosaic_on_press(event)

    def _on_drag(self, event):
        if event.state & 0x4:  # Ctrl held
            return
        if self._tool == "crop":
            self._crop_on_drag(event)
        elif self._tool == "mosaic" and self._mosaic_painting:
            self._apply_mosaic_at(event.x, event.y)
            self._schedule_refresh()

    def _on_release(self, event):
        if event.state & 0x4:
            return
        if self._tool == "crop":
            self._crop_on_release(event)
        elif self._tool == "mosaic":
            self._mosaic_painting = False
            self._refresh_canvas()

    def _on_double_click(self, event):
        if self._tool == "crop" and self._crop_phase == "placed":
            self._apply_crop()

    def _on_key_escape(self, _event):
        if self._tool == "crop" and self._crop_phase == "placed":
            self._cancel_crop()

    def _on_key_return(self, _event):
        if self._tool == "crop" and self._crop_phase == "placed":
            self._apply_crop()

    # ==================== CROP ====================

    def _crop_on_press(self, event):
        if self._crop_phase == "placed" and self._crop_image_rect:
            ix1, iy1, ix2, iy2 = self._crop_image_rect
            cx1, cy1 = self._image_to_canvas(ix1, iy1)
            cx2, cy2 = self._image_to_canvas(ix2, iy2)
            if cx1 <= event.x <= cx2 and cy1 <= event.y <= cy2:
                self._crop_phase = "moving"
                self._crop_move_start = (event.x, event.y)
                return
            else:
                self._cancel_crop()

        self._crop_phase = "drawing"
        self._drag_start = (event.x, event.y)
        if self._rect_id:
            self._canvas.delete(self._rect_id)
        self._rect_id = self._canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="#00d4aa", width=2, dash=(4, 4),
        )

    def _crop_on_drag(self, event):
        if self._crop_phase == "drawing" and self._drag_start:
            sx, sy = self._drag_start
            ex, ey = self._constrain(sx, sy, event.x, event.y, event.state)
            if self._rect_id:
                self._canvas.coords(self._rect_id, sx, sy, ex, ey)
        elif self._crop_phase == "moving" and self._crop_move_start and self._crop_image_rect:
            dx_img = (event.x - self._crop_move_start[0]) / self._scale
            dy_img = (event.y - self._crop_move_start[1]) / self._scale
            ix1, iy1, ix2, iy2 = self._crop_image_rect
            self._crop_image_rect = (ix1 + dx_img, iy1 + dy_img,
                                     ix2 + dx_img, iy2 + dy_img)
            cx1, cy1 = self._image_to_canvas(self._crop_image_rect[0], self._crop_image_rect[1])
            cx2, cy2 = self._image_to_canvas(self._crop_image_rect[2], self._crop_image_rect[3])
            if self._rect_id:
                self._canvas.coords(self._rect_id, cx1, cy1, cx2, cy2)
            self._crop_move_start = (event.x, event.y)

    def _crop_on_release(self, event):
        if self._crop_phase == "drawing" and self._drag_start:
            sx, sy = self._drag_start
            ex, ey = self._constrain(sx, sy, event.x, event.y, event.state)
            self._drag_start = None
            rx1, ry1 = min(sx, ex), min(sy, ey)
            rx2, ry2 = max(sx, ex), max(sy, ey)
            if rx2 - rx1 >= 10 and ry2 - ry1 >= 10:
                ix1, iy1 = self._canvas_to_image(rx1, ry1)
                ix2, iy2 = self._canvas_to_image(rx2, ry2)
                self._crop_image_rect = (ix1, iy1, ix2, iy2)
                if self._rect_id:
                    self._canvas.coords(self._rect_id, rx1, ry1, rx2, ry2)
                    self._canvas.itemconfig(self._rect_id, dash=(), width=2)
                self._crop_phase = "placed"
                self._canvas.config(cursor="fleur")
                self._hint_var.set("")
            else:
                self._cancel_crop()
        elif self._crop_phase == "moving":
            self._crop_phase = "placed"

    def _apply_crop(self):
        if self._crop_image_rect:
            x1, y1, x2, y2 = [int(v) for v in self._crop_image_rect]
            iw, ih = self._working.size
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(iw, x2), min(ih, y2)
            if x2 - x1 >= 4 and y2 - y1 >= 4:
                self._history.append(self._working.copy())
                self._working = self._working.crop((x1, y1, x2, y2))
        self._cleanup_crop()
        self._refresh_canvas()

    def _cancel_crop(self):
        self._cleanup_crop()
        self._hint_var.set("Drag to crop  (Shift \u2192 square)")

    def _cleanup_crop(self):
        if self._rect_id:
            self._canvas.delete(self._rect_id)
            self._rect_id = None
        self._crop_phase = None
        self._crop_image_rect = None
        self._drag_start = None
        self._crop_move_start = None
        if self._tool == "crop":
            self._canvas.config(cursor="crosshair")

    @staticmethod
    def _constrain(sx, sy, ex, ey, state):
        if state & 0x1:
            dx, dy = ex - sx, ey - sy
            size = max(abs(dx), abs(dy))
            ex = sx + (size if dx >= 0 else -size)
            ey = sy + (size if dy >= 0 else -size)
        return ex, ey

    # ==================== MOSAIC ====================

    def _mosaic_on_press(self, event):
        self._history.append(self._working.copy())
        self._mosaic_painting = True
        self._apply_mosaic_at(event.x, event.y)
        self._schedule_refresh()

    def _apply_mosaic_at(self, cx, cy):
        ix, iy = self._canvas_to_image(cx, cy)
        r = self._mosaic_radius
        iw, ih = self._working.size
        x1, y1 = max(0, ix - r), max(0, iy - r)
        x2, y2 = min(iw, ix + r), min(ih, iy + r)
        rw, rh = x2 - x1, y2 - y1
        if rw < _MOSAIC_BLOCK or rh < _MOSAIC_BLOCK:
            return
        region = self._working.crop((x1, y1, x2, y2))
        sw, sh = max(1, rw // _MOSAIC_BLOCK), max(1, rh // _MOSAIC_BLOCK)
        mosaic = region.resize((sw, sh), Image.NEAREST).resize((rw, rh), Image.NEAREST)
        self._working.paste(mosaic, (x1, y1))

    def _schedule_refresh(self):
        if not self._refresh_scheduled:
            self._refresh_scheduled = True
            self.after(40, self._refresh_canvas)

    # -- reset --

    def _reset(self):
        if self._original is None:
            return
        if self._crop_phase == "placed":
            self._cleanup_crop()
        self._working = self._original.copy()
        self._history = []
        self._edit_zoom = 1.0
        self._edit_pan_x = 0
        self._edit_pan_y = 0
        self._refresh_canvas()

    # -- save / cancel --

    def _do_save(self):
        from tkinter import filedialog

        if self._crop_phase == "placed" and self._crop_image_rect:
            x1, y1, x2, y2 = [int(v) for v in self._crop_image_rect]
            iw, ih = self._working.size
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(iw, x2), min(ih, y2)
            if x2 - x1 >= 4 and y2 - y1 >= 4:
                self._working = self._working.crop((x1, y1, x2, y2))
            self._cleanup_crop()

        fmt = self._format_var.get()
        ext = f".{fmt}"
        stem = self._original_stem or "output"
        default_name = f"{stem}_nobg_edit{ext}"
        path = filedialog.asksaveasfilename(
            title="Save edited image", defaultextension=ext, initialfile=default_name,
            filetypes=[(f"{fmt.upper()} files", f"*{ext}"), ("All files", "*.*")],
        )
        if not path:
            return
        # composite on background if selected, otherwise transparent
        if self._bg_color is None:
            save_img = self._working
        else:
            save_img = _composite(self._working, self._bg_color)
        if fmt == "webp":
            save_img.save(path, format="WEBP", lossless=True)
        else:
            save_img.save(path, format="PNG")
        # stay in edit mode (don't call _on_save_cb)

    def _do_cancel(self):
        self._working = None
        self._history = []
        self._on_cancel_cb()
