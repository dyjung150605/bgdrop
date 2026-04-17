"""Modal thumbnail gallery for auto combination selection."""
import random
import tkinter as tk
import numpy as np
from PIL import Image, ImageTk

from ui.platform import FONT_FAMILY
from ui.tooltip import ToolTip


# Playful present-progressive phrases inspired by Claude Code's "thinking" UI.
THINKING_WORDS = [
    "Accomplishing", "Assembling", "Baking", "Brewing", "Calibrating",
    "Channeling", "Churning", "Coalescing", "Cogitating", "Composing",
    "Computing", "Concocting", "Conjuring", "Contemplating", "Cooking",
    "Crafting", "Decoding", "Deliberating", "Distilling", "Divining",
    "Drafting", "Dreaming", "Envisioning", "Exploring", "Fabricating",
    "Fermenting", "Finagling", "Forging", "Formulating", "Germinating",
    "Harmonizing", "Hatching", "Ideating", "Imagining", "Incubating",
    "Inferring", "Kindling", "Marinating", "Meditating", "Mulling",
    "Musing", "Navigating", "Noodling", "Orchestrating", "Parsing",
    "Percolating", "Polishing", "Pondering", "Puzzling", "Refining",
    "Reflecting", "Rendering", "Ruminating", "Scheming", "Shaping",
    "Sifting", "Simmering", "Sleuthing", "Spinning", "Stewing",
    "Strategizing", "Synthesizing", "Tailoring", "Tinkering", "Tuning",
    "Unraveling", "Weaving", "Whipping", "Whittling", "Wondering",
    "Working", "Wrangling", "Wrestling",
]

# Claude Code signature warm copper/amber
CLAUDE_ACCENT = "#d97757"


MODEL_DISPLAY = {
    "isnet-general-use": "ISNet",
    "u2net": "U2Net",
    "u2net_human_seg": "U2Net Human",
}


def _combo_stack_text(combo):
    """Human-readable stack summary for tooltip."""
    model_name = MODEL_DISPLAY.get(combo["model"], combo["model"])
    on = lambda b: "ON" if b else "OFF"  # noqa: E731
    return (
        f"모델: {model_name}\n"
        f"• Post Process Mask: {on(combo['post_process'])}\n"
        f"• Alpha Clean: {on(combo['alpha_clean'])}\n"
        f"• Alpha Matting: {on(combo['alpha_matting'])}"
    )


THUMB_MAX = 240  # max thumbnail dimension (preview image)


def _make_checker(size, cell=10):
    """Simple two-tone checker background (numpy for speed)."""
    w, h = size
    xi = np.arange(w) // cell
    yi = np.arange(h) // cell
    mask = ((xi[None, :] + yi[:, None]) % 2) == 0
    arr = np.empty((h, w, 3), dtype=np.uint8)
    arr[mask] = (46, 46, 46)
    arr[~mask] = (60, 60, 60)
    return Image.fromarray(arr)


def _hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _composite_over_bg(rgba_thumb, bg_color):
    """Composite an RGBA thumbnail over a solid color, or over a checker if None."""
    w, h = rgba_thumb.size
    if bg_color is None:
        bg = _make_checker((w, h))
    else:
        bg = Image.new("RGB", (w, h), _hex_to_rgb(bg_color))
    bg.paste(rgba_thumb, (0, 0), rgba_thumb)
    return bg


def compute_thumb_size(source_w, source_h, preview_size=512, thumb_max=THUMB_MAX):
    """Predict the final thumbnail size produced by the simulator + dialog pipeline.

    Simulator first shrinks the source to fit `preview_size`, then the dialog
    shrinks the result to fit `thumb_max`. Both steps preserve aspect ratio.
    """
    w, h = source_w, source_h
    if max(w, h) > preview_size:
        s = preview_size / max(w, h)
        w, h = max(1, int(w * s)), max(1, int(h * s))
    if max(w, h) > thumb_max:
        s = thumb_max / max(w, h)
        w, h = max(1, int(w * s)), max(1, int(h * s))
    return w, h


class AutoSelectorDialog:
    """Modal dialog that shows candidate results as a clickable grid."""

    def __init__(self, parent, on_pick, on_close, bg_color=None):
        self.parent = parent
        self.on_pick = on_pick         # may be called multiple times
        self.on_close = on_close       # called once when dialog is dismissed
        self._bg_color = bg_color
        self._slots = {}   # key -> dict(frame, img_label, text_label, combo, rgba, tooltip)
        self._images = {}  # key -> PhotoImage (keep ref)
        self._placeholder_photo = None
        self._base_thumb_size = (240, 240)  # overwritten by reserve_slots
        self._current_thumb_size = (240, 240)
        self._resize_timer = None
        self._closed = False
        self._selected_key = None
        # Resize tracking: only react to explicit user resizes, not layout-driven ones
        self._resize_armed = False
        self._last_applied_width = 0
        self._last_applied_height = 0

        self.top = tk.Toplevel(parent)
        self.top.title("Auto Preset  —  Smart Match")
        self.top.configure(bg="#1e1e1e")
        self.top.resizable(True, True)
        self.top.minsize(420, 500)
        try:
            self.top.transient(parent)
        except tk.TclError:
            pass
        self.top.protocol("WM_DELETE_WINDOW", self._close)
        self.top.bind("<Configure>", self._on_configure)
        self.top.after(10, self._place_beside_parent)

        self._header_var = tk.StringVar(
            value="결과를 시뮬레이션 중입니다. 원하는 썸네일을 클릭하세요."
        )
        header = tk.Label(
            self.top,
            textvariable=self._header_var,
            bg="#1e1e1e", fg="#e0e0e0",
            font=(FONT_FAMILY, 11, "bold"),
            padx=16, pady=10,
        )
        header.pack(side=tk.TOP, fill=tk.X)

        self._grid = tk.Frame(self.top, bg="#1e1e1e")
        self._grid.pack(side=tk.TOP, padx=16, pady=4)

        btn_frame = tk.Frame(self.top, bg="#1e1e1e")
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=(8, 12))
        tk.Button(
            btn_frame, text="닫기",
            bg="#2a2a2a", fg="#e0e0e0",
            activebackground="#3a3a3a", activeforeground="#ffffff",
            relief=tk.FLAT, padx=14, pady=6,
            font=(FONT_FAMILY, 9), command=self._close,
        ).pack(side=tk.RIGHT)

    def _place_beside_parent(self):
        """Place the dialog immediately to the right of the main window."""
        try:
            self.parent.update_idletasks()
            px = self.parent.winfo_x()
            py = self.parent.winfo_y()
            pw = self.parent.winfo_width()
            # Clamp to screen width so the dialog stays visible.
            sw = self.top.winfo_screenwidth()
            dw = self.top.winfo_reqwidth() or 560
            x = px + pw + 4
            if x + dw > sw:
                x = max(0, sw - dw)
            self.top.geometry(f"+{x}+{py}")
        except tk.TclError:
            pass

    def reserve_slots(self, candidates, thumb_size):
        """Pre-create placeholders in a 2-column grid.

        thumb_size is the initial (w, h) — acts as the aspect-ratio reference
        used whenever the window is resized.
        """
        self._base_thumb_size = thumb_size
        self._current_thumb_size = thumb_size
        self._rebuild_placeholder()

        for i, combo in enumerate(candidates):
            row, col = i // 2, i % 2
            slot = tk.Frame(
                self._grid, bg="#252525", padx=8, pady=8,
                highlightthickness=2, highlightbackground="#252525",
            )
            slot.grid(row=row, column=col, padx=6, pady=6)

            img_label = tk.Label(
                slot, image=self._placeholder_photo,
                text=f"{random.choice(THINKING_WORDS)}…",
                compound=tk.CENTER,
                bg="#252525", fg=CLAUDE_ACCENT,
                font=(FONT_FAMILY, 12, "italic"),
            )
            img_label.pack()

            text_label = tk.Label(
                slot, text=combo["label"],
                bg="#252525", fg="#e0e0e0",
                font=(FONT_FAMILY, 10),
            )
            text_label.pack(pady=(6, 0))

            # Stack tooltip on every interactive element so it's always discoverable
            tip_text = _combo_stack_text(combo)
            ToolTip(slot, tip_text)
            ToolTip(img_label, tip_text)
            ToolTip(text_label, tip_text)

            self._slots[combo["key"]] = {
                "frame": slot,
                "img_label": img_label,
                "text_label": text_label,
                "combo": combo,
                "rgba": None,  # cached simulator output (≤ 512px), set on show_result
                "tick_timer": None,  # per-slot rotation timer id
            }

        # Arm resize detection *after* initial layout settles.
        # This avoids a feedback loop where sim-driven content changes trigger reflow.
        self.top.after(250, self._arm_resize)
        # Kick off per-slot thinking-word rotations with staggered first ticks
        # so the slots don't all change in unison.
        for key in self._slots:
            delay = int(random.uniform(500, 1500))
            self._slots[key]["tick_timer"] = self.top.after(
                delay, lambda k=key: self._rotate_slot(k)
            )

    def _arm_resize(self):
        if self._closed:
            return
        self._last_applied_width = self.top.winfo_width()
        self._last_applied_height = self.top.winfo_height()
        self._resize_armed = True

    def _rebuild_placeholder(self):
        w, h = self._current_thumb_size
        placeholder = Image.new("RGB", (max(1, w), max(1, h)), (40, 40, 40))
        self._placeholder_photo = ImageTk.PhotoImage(placeholder)
        for slot in self._slots.values():
            if slot["rgba"] is None:
                slot["img_label"].config(image=self._placeholder_photo)

    def show_result(self, key, rgba_image):
        if self._closed or key not in self._slots:
            return
        slot = self._slots[key]
        # Store full simulator output so we can resample at any display size.
        slot["rgba"] = rgba_image.copy()
        self._render_slot(key)
        combo = slot["combo"]
        for w in (slot["frame"], slot["img_label"], slot["text_label"]):
            w.bind("<Button-1>", lambda _e, c=combo: self._pick(c))
            w.config(cursor="hand2")
        slot["frame"].bind(
            "<Enter>", lambda _e, k=key: self._on_hover(k, True),
        )
        slot["frame"].bind(
            "<Leave>", lambda _e, k=key: self._on_hover(k, False),
        )

    def _on_hover(self, key, entering):
        """Hover highlight — preserve selection color on the picked slot."""
        slot = self._slots.get(key)
        if not slot:
            return
        frame = slot["frame"]
        if entering:
            frame.config(highlightbackground="#00d4aa")
        else:
            # Restore: green if this is the selected pick, gray otherwise.
            color = "#00d4aa" if key == self._selected_key else "#252525"
            frame.config(highlightbackground=color)

    def _render_slot(self, key):
        """Resample the cached RGBA to current thumb size and composite over BG."""
        slot = self._slots.get(key)
        if not slot or slot["rgba"] is None:
            return
        target_w, target_h = self._current_thumb_size
        src = slot["rgba"]
        sw, sh = src.size
        # Fit into target while preserving aspect ratio
        if sw == 0 or sh == 0:
            return
        scale = min(target_w / sw, target_h / sh)
        new_w = max(1, int(sw * scale))
        new_h = max(1, int(sh * scale))
        resized = src.resize((new_w, new_h), Image.LANCZOS)
        bg = _composite_over_bg(resized, self._bg_color)
        photo = ImageTk.PhotoImage(bg)
        self._images[key] = photo
        slot["img_label"].config(image=photo, text="", compound=tk.NONE)

    def update_bg_color(self, color):
        """Called from outside when the main window's BG selector changes."""
        if self._closed:
            return
        self._bg_color = color
        for key in self._slots:
            self._render_slot(key)

    def _on_configure(self, event):
        """Window resized — only act on explicit user resizes, not layout reflow."""
        if self._closed or event.widget is not self.top or not self._resize_armed:
            return
        # Ignore small deltas (likely content-driven reflow, not a user drag)
        dw = abs(event.width - self._last_applied_width)
        dh = abs(event.height - self._last_applied_height)
        if dw < 24 and dh < 24:
            return
        self._last_applied_width = event.width
        self._last_applied_height = event.height
        if self._resize_timer is not None:
            try:
                self.top.after_cancel(self._resize_timer)
            except tk.TclError:
                pass
        self._resize_timer = self.top.after(120, self._relayout)

    def _relayout(self):
        """Compute new thumb cell size fitting both width and height constraints."""
        self._resize_timer = None
        if self._closed or not self._slots:
            return
        window_w = self.top.winfo_width()
        window_h = self.top.winfo_height()

        # Horizontal chrome per row:
        #   outer padx 16*2 + grid cell padx 6*2 per cell * 2 cells
        #   + slot padx 8*2 per cell * 2 + highlightthickness 2*2 per cell * 2 ≈ 96 px
        avail_w_per_cell = max(1, (window_w - 96) // 2)
        # Vertical chrome total (not per cell): header ~40 + grid outer pady ~8
        #   + slot (text label + paddings) ~40 per slot * 2 rows
        #   + grid row pady 12 * 2 rows + button bar ~50  ≈ 200 px
        avail_h_per_cell = max(1, (window_h - 200) // 2)

        base_w, base_h = self._base_thumb_size
        if base_w <= 0 or base_h <= 0:
            return
        scale = min(avail_w_per_cell / base_w, avail_h_per_cell / base_h)
        # Minimum scale so cells don't shrink to nothing
        scale = max(scale, 120 / base_w)
        cell_w = max(1, int(base_w * scale))
        cell_h = max(1, int(base_h * scale))
        if (cell_w, cell_h) == self._current_thumb_size:
            return
        self._current_thumb_size = (cell_w, cell_h)
        self._rebuild_placeholder()
        for key in self._slots:
            self._render_slot(key)
        # Record the size we've applied so the subsequent content-driven
        # Configure events are ignored.
        self._last_applied_width = self.top.winfo_width()
        self._last_applied_height = self.top.winfo_height()

    def show_error(self, key, err):
        if self._closed or key not in self._slots:
            return
        msg = err if len(err) < 40 else err[:37] + "…"
        self._slots[key]["img_label"].config(text=f"에러: {msg}", fg="#ff6b6b")

    def set_complete(self):
        """Called when all simulations finish (success or error)."""
        if self._closed:
            return
        self._cancel_all_ticks()
        if self._selected_key is None:
            self._header_var.set("완료  —  썸네일을 클릭해 선택하세요.")

    def _rotate_slot(self, key):
        """Rotate one slot's placeholder text independently, then self-reschedule."""
        if self._closed:
            return
        slot = self._slots.get(key)
        if not slot:
            return
        slot["tick_timer"] = None
        if slot["rgba"] is not None:
            return  # already filled — stop rotating this slot
        slot["img_label"].config(text=f"{random.choice(THINKING_WORDS)}…")
        # Triangular distribution: lower=2400/2, upper=2400*1.25, mode=2400
        # Interpreted per user spec: low 1200, mode 2400, high 3000
        delay = int(random.triangular(1200, 3000, 2400))
        slot["tick_timer"] = self.top.after(
            delay, lambda k=key: self._rotate_slot(k)
        )

    def _cancel_all_ticks(self):
        for slot in self._slots.values():
            t = slot.get("tick_timer")
            if t is not None:
                try:
                    self.top.after_cancel(t)
                except tk.TclError:
                    pass
                slot["tick_timer"] = None

    def _pick(self, combo):
        """User clicked a thumbnail. Dialog stays open for further comparison."""
        if self._closed:
            return
        key = combo["key"]
        # Unhighlight previous selection
        if self._selected_key and self._selected_key in self._slots:
            prev = self._slots[self._selected_key]["frame"]
            prev.config(highlightbackground="#252525")
        self._selected_key = key
        # Persistent green border on the selected slot
        slot = self._slots.get(key)
        if slot:
            slot["frame"].config(highlightbackground="#00d4aa")
        self._header_var.set(
            f"선택: {combo['label']}  —  다른 썸네일을 클릭해 비교해보세요."
        )
        self.on_pick(combo)

    def _close(self):
        if self._closed:
            return
        self._closed = True
        self._cancel_all_ticks()
        self.top.destroy()
        self.on_close(self._selected_key is not None)
