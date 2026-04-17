import os
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageOps

import ui.platform as platform
from ui.platform import FONT_FAMILY
from ui.drop_zone import DropZone, VALID_EXTENSIONS
from ui.result_panel import ResultPanel
from ui.edit_panel import EditPanel
from ui.tooltip import ToolTip
from core.remover import BackgroundRemover, AVAILABLE_MODELS, _clean_alpha
from core.auto_selector import analyze_image, pick_candidates
from core.simulator import simulate_async
from ui.auto_dialog import AutoSelectorDialog, compute_thumb_size


class AppWindow:
    """Main application controller that wires up all UI components."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.configure(bg="#1e1e1e")
        self.remover = BackgroundRemover()
        self._processing = False
        self._last_filepath = None
        self._source_image = None
        self._process_image = None
        self._raw_result = None
        self._suppress_trace = False
        self._auto_dialog = None
        self._sim_gen = 0  # bumped on every auto flow; stale callbacks are dropped

        # ===== main view widgets =====
        self._main_widgets = []

        # -- status bar (pack BOTTOM first — always visible) --
        self._status_var = tk.StringVar(value="Loading model...")
        self._status_frame = tk.Frame(root, bg="#181818")
        self._status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self._status_bar = tk.Label(
            self._status_frame, textvariable=self._status_var,
            bg="#181818", fg="#888888", anchor=tk.W,
            font=(FONT_FAMILY, 9), padx=8, pady=4,
        )
        self._status_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            self._status_frame, text="v1.0", bg="#181818", fg="#555555",
            font=(FONT_FAMILY, 8), padx=8, pady=4,
        ).pack(side=tk.RIGHT)

        # -- pipeline controls (pack BOTTOM — sticks above status bar) --
        self._pipe_frame = tk.Frame(root, bg="#1e1e1e")
        self._pipe_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=(4, 2))
        self._main_widgets.append(self._pipe_frame)

        self._build_pipeline(self._pipe_frame)

        # -- drop zone (pack TOP — fixed height) --
        self.drop_zone = DropZone(
            root, on_file_dropped=self._on_file, height=100,
        )
        self.drop_zone.pack(side=tk.TOP, padx=20, pady=(10, 4), fill=tk.X)
        self._main_widgets.append(self.drop_zone)

        # -- result panel (fills remaining space) --
        self.result_panel = ResultPanel(root, on_edit=self._enter_edit,
                                        on_file_dropped=self._on_file)
        self.result_panel.pack(side=tk.TOP, padx=20, pady=(0, 4),
                               fill=tk.BOTH, expand=True)
        self.result_panel.set_bg_listener(self._on_bg_color_change)
        self._main_widgets.append(self.result_panel)

        # ===== edit panel (created once, shown/hidden) =====
        self.edit_panel = EditPanel(
            root,
            on_save=self._exit_edit,
            on_cancel=self._exit_edit,
        )

        # -- init default model --
        self._load_model(AVAILABLE_MODELS[0][0])

    def _build_pipeline(self, frame):
        # Auto Selector toggle (left-most — overrides the manual pipeline on file drop)
        info_auto = tk.Label(frame, text="\u24d8", bg="#1e1e1e", fg="#00d4aa",
                             font=(FONT_FAMILY, 11), cursor="hand2")
        info_auto.pack(side=tk.LEFT)
        ToolTip(info_auto,
                "Auto Selector\n"
                "\uc774\ubbf8\uc9c0\ub97c \ubd84\uc11d\ud574 \ucd94\ucc9c \uc870\ud569 3~4\uac1c\ub97c\n"
                "\ucd95\uc18c\ubcf8\uc73c\ub85c \uc2dc\ubbac\ub808\uc774\uc158\ud558\uace0,\n"
                "\uc0ac\uc6a9\uc790\uac00 \uc378\ub124\uc77c\uc744 \ub354\ube14\ud074\ub9ad\ud558\uba74\n"
                "\uc6d0\ubcf8 \ud574\uc0c1\ub3c4\uc5d0 \uc801\uc6a9\ub429\ub2c8\ub2e4.\n"
                "\uaebc\uc838 \uc788\uc73c\uba74 \uc9c1\uc811 \uc124\uc815 \uc0ac\uc6a9.")
        self._auto_var = tk.BooleanVar(value=False)
        self._auto_var.trace_add("write", self._on_auto_toggle)
        tk.Checkbutton(
            frame, text="\U0001fa84 Auto", variable=self._auto_var,
            bg="#1e1e1e", fg="#00d4aa", selectcolor="#2a2a2a",
            activebackground="#1e1e1e", activeforeground="#00ffcc",
            font=(FONT_FAMILY, 9, "bold"),
        ).pack(side=tk.LEFT, padx=(2, 10))

        tk.Label(frame, text="\u2502", bg="#1e1e1e", fg="#333333",
                 font=(FONT_FAMILY, 10)).pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(
            frame, text="Pipeline:", bg="#1e1e1e", fg="#666666",
            font=(FONT_FAMILY, 8),
        ).pack(side=tk.LEFT, padx=(0, 6))

        # Model selector + info
        info1 = tk.Label(frame, text="\u24d8", bg="#1e1e1e", fg="#00d4aa",
                         font=(FONT_FAMILY, 11), cursor="hand2")
        info1.pack(side=tk.LEFT)
        ToolTip(info1,
                "AI \ubaa8\ub378 \uc120\ud0dd\n"
                "\u2022 ISNet: \ub192\uc740 \ub514\ud14c\uc77c, \uac00\ub294 \uacbd\uacc4 \uc6b0\uc218\n"
                "\u2022 U2Net: \ubc94\uc6a9, \ube60\ub978 \uc18d\ub3c4\n"
                "\u2022 U2Net Portrait: \uc778\ubb3c \uc804\uc6a9 \ucd5c\uc801\ud654")

        self._model_var = tk.StringVar(value=AVAILABLE_MODELS[0][0])
        self._model_combo = ttk.Combobox(
            frame, textvariable=self._model_var, state="readonly", width=20,
            values=[f"{n}  \u2014  {l}" for n, l in AVAILABLE_MODELS],
        )
        self._model_combo.current(0)
        self._model_combo.pack(side=tk.LEFT, padx=(2, 8))
        self._model_combo.bind("<<ComboboxSelected>>", self._on_model_change)

        tk.Label(frame, text="\u25b6", bg="#1e1e1e", fg="#555555",
                 font=(FONT_FAMILY, 7)).pack(side=tk.LEFT, padx=(0, 6))

        # Post Process Mask + info (rembg 내장 모폴로지)
        info_pm = tk.Label(frame, text="\u24d8", bg="#1e1e1e", fg="#00d4aa",
                           font=(FONT_FAMILY, 11), cursor="hand2")
        info_pm.pack(side=tk.LEFT)
        ToolTip(info_pm,
                "Post Process Mask\n"
                "rembg \ub0b4\uc7a5 \ubaa8\ud3f4\ub85c\uc9c0 \uc5f0\uc0b0\n"
                "\uce68\uc2dd/\ud321\ucc3d\uc73c\ub85c \ub9c8\uc2a4\ud06c \uacbd\uacc4 \uc815\ub9ac\n"
                "\ud070 \ub369\uc5b4\ub9ac \ub178\uc774\uc988\uc640 \uad6c\uba4d \uc81c\uac70")
        _pipe_default = not platform.IS_MACOS
        self._postmask_var = tk.BooleanVar(value=_pipe_default)
        self._postmask_var.trace_add("write", self._on_reprocess_toggle)
        tk.Checkbutton(
            frame, text="Post Process Mask", variable=self._postmask_var,
            bg="#1e1e1e", fg="#e0e0e0", selectcolor="#2a2a2a",
            activebackground="#1e1e1e", activeforeground="#00d4aa",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=(0, 6))

        tk.Label(frame, text="\u25b6", bg="#1e1e1e", fg="#555555",
                 font=(FONT_FAMILY, 7)).pack(side=tk.LEFT, padx=(0, 6))

        # Alpha Clean + info
        info_ac = tk.Label(frame, text="\u24d8", bg="#1e1e1e", fg="#00d4aa",
                           font=(FONT_FAMILY, 11), cursor="hand2")
        info_ac.pack(side=tk.LEFT)
        ToolTip(info_ac,
                "Alpha Clean\n"
                "\ubc18\ud22c\uba85 \ud5e4\uc77c\ub85c(\ubc88\uc9d0) \uc81c\uac70\n"
                "alpha < 80 \u2192 \uc644\uc804 \ud22c\uba85\n"
                "alpha > 200 \u2192 \uc644\uc804 \ubd88\ud22c\uba85\n"
                "Post Process Mask\uc640 \ubcd1\uc6a9 \uc2dc \uc2dc\ub108\uc9c0 \ud6a8\uacfc")
        self._alpha_clean_var = tk.BooleanVar(value=_pipe_default)
        self._alpha_clean_var.trace_add("write", self._on_alpha_clean_toggle)
        tk.Checkbutton(
            frame, text="Alpha Clean", variable=self._alpha_clean_var,
            bg="#1e1e1e", fg="#e0e0e0", selectcolor="#2a2a2a",
            activebackground="#1e1e1e", activeforeground="#00d4aa",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT, padx=(0, 6))

        tk.Label(frame, text="\u25b6", bg="#1e1e1e", fg="#555555",
                 font=(FONT_FAMILY, 7)).pack(side=tk.LEFT, padx=(0, 6))

        # Alpha Matting + info
        info_am = tk.Label(frame, text="\u24d8", bg="#1e1e1e", fg="#00d4aa",
                           font=(FONT_FAMILY, 11), cursor="hand2")
        info_am.pack(side=tk.LEFT)
        ToolTip(info_am,
                "Alpha Matting\n"
                "\uba38\ub9ac\uce74\ub77d/\ud138 \ub4f1 \uac00\ub294 \ub514\ud14c\uc77c\uc758\n"
                "\uacbd\uacc4\ub97c \uc815\ubc00\ud558\uac8c \ub2e4\ub46f\uc74c\n"
                "\u26a0 2~3\ubc30 \ub290\ub9bc")
        self._alpha_matting_var = tk.BooleanVar(value=False)
        self._alpha_matting_var.trace_add("write", self._on_reprocess_toggle)
        tk.Checkbutton(
            frame, text="Alpha Matting", variable=self._alpha_matting_var,
            bg="#1e1e1e", fg="#e0e0e0", selectcolor="#2a2a2a",
            activebackground="#1e1e1e", activeforeground="#00d4aa",
            font=(FONT_FAMILY, 9),
        ).pack(side=tk.LEFT)

    # ===== view switching =====

    def _enter_edit(self, result_image, format_val, stem):
        for w in self._main_widgets:
            w.pack_forget()
        self.edit_panel.pack(side=tk.TOP, padx=10, pady=(6, 0),
                             fill=tk.BOTH, expand=True,
                             before=self._status_frame)
        self.edit_panel.load_image(result_image, format_val, stem)
        self._set_status("Edit mode  \u2014  Crop / Mosaic")

    def _exit_edit(self):
        self.edit_panel.pack_forget()
        # re-pack main widgets in correct order
        self._pipe_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=(4, 2))
        self.drop_zone.pack(side=tk.TOP, padx=20, pady=(10, 4), fill=tk.X)
        self.result_panel.pack(side=tk.TOP, padx=20, pady=(0, 4),
                               fill=tk.BOTH, expand=True)
        self._set_status("Done!  Drag another image or click Save.")

    # ===== model management =====

    def _load_model(self, model_name):
        self._set_status(f"Loading {model_name}...")
        self._model_combo.config(state="disabled")
        self.remover.init_session(
            model_name,
            on_ready=self._on_session_ready,
            on_error=self._on_session_error,
        )

    def _on_model_change(self, _event):
        selected = self._model_combo.get()
        model_name = selected.split("  \u2014")[0].strip()
        if model_name != self.remover.current_model:
            self._load_model(model_name)
            if self._source_image is not None:
                self._pending_reprocess = True

    # ===== live toggle =====

    def _on_alpha_clean_toggle(self, *_args):
        if self._suppress_trace or self._raw_result is None:
            return
        state = "ON" if self._alpha_clean_var.get() else "OFF"
        self._set_status(f"Alpha Clean {state}")
        self._apply_final_and_show()

    def _on_reprocess_toggle(self, *_args):
        if self._suppress_trace:
            return
        if self._process_image is not None and not self._processing:
            state = "ON" if self._alpha_matting_var.get() else "OFF"
            self._set_status(f"Alpha Matting {state} — reprocessing...")
            self._run_removal(self._process_image)

    def _apply_final_and_show(self):
        if self._alpha_clean_var.get():
            final = _clean_alpha(self._raw_result.copy())
        else:
            final = self._raw_result.copy()
        self.result_panel.show_after(final)

    # ===== callbacks =====

    def _set_status(self, text):
        self._status_var.set(text)

    def _on_session_ready(self, mode, model_name):
        label = "Online" if mode == "online" else "Offline"
        self.root.after(0, self._set_status, f"Ready  [{model_name} / {label}]")
        self.root.after(0, self._model_combo.config, {"state": "readonly"})
        if getattr(self, "_pending_reprocess", False) and self._process_image is not None:
            self._pending_reprocess = False
            self.root.after(0, self._run_removal, self._process_image)

    def _on_session_error(self, err):
        self.root.after(0, self._set_status, f"Model load error: {err}")
        self.root.after(0, self._model_combo.config, {"state": "readonly"})
        self._pending_reprocess = False

    def _on_file(self, filepath):
        if self._processing:
            return

        ext = os.path.splitext(filepath)[1].lower()
        if ext not in VALID_EXTENSIONS:
            self._set_status(f"Unsupported format: {ext}")
            return

        if self.remover.session is None:
            self._set_status("Model still loading, please wait...")
            return

        self._last_filepath = filepath
        stem = os.path.splitext(os.path.basename(filepath))[0]
        self.result_panel.set_original_stem(stem)

        try:
            img = Image.open(filepath)
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
        except Exception as e:
            self._set_status(f"Cannot open image: {e}")
            return

        # Downscale if too large to prevent excessive memory usage
        _MAX_DIM = 4096
        if max(img.size) > _MAX_DIM:
            img.thumbnail((_MAX_DIM, _MAX_DIM), Image.LANCZOS)
            self._set_status(f"Image resized to {img.size[0]}×{img.size[1]} (max {_MAX_DIM}px)")

        self._source_image = img                    # original (RGBA OK) for Before preview
        self._process_image = img.convert("RGB")     # RGB for rembg (always consistent)
        self.result_panel.show_before(img)

        if self._auto_var.get():
            self._start_auto_flow()
        else:
            # If a previous auto dialog is still open, close it — we're switching to manual.
            self._discard_auto_dialog()
            self._run_removal(self._process_image)

    # ===== auto selector flow =====

    def _on_auto_toggle(self, *_args):
        """Trigger auto flow when toggled ON with an image already loaded."""
        if self._suppress_trace:
            return
        if (self._auto_var.get() and self._process_image is not None
                and not self._processing and self._auto_dialog is None):
            self._start_auto_flow()

    def _start_auto_flow(self):
        """Analyze image, pick candidates, simulate on a downscaled copy,
        show thumbnails, apply chosen combo to the full-res image."""
        # If a previous dialog is still open (e.g. user dropped a new image),
        # discard it silently — stale simulation callbacks are filtered by _sim_gen.
        self._discard_auto_dialog()

        self._set_status("분석 중…")
        features = analyze_image(self._process_image)
        candidates = pick_candidates(features)
        if not candidates:
            self._run_removal(self._process_image)
            return

        dialog = AutoSelectorDialog(
            self.root,
            on_pick=self._on_auto_pick,
            on_close=self._on_auto_close,
            bg_color=self.result_panel.get_bg_color(),
        )
        thumb_size = compute_thumb_size(*self._process_image.size)
        dialog.reserve_slots(candidates, thumb_size=thumb_size)
        self._auto_dialog = dialog

        self._sim_gen += 1
        gen = self._sim_gen
        self._set_status(f"시뮬레이션 시작 ({len(candidates)}개 후보)…")

        simulate_async(
            self._process_image,
            candidates,
            ensure_session=self.remover.ensure_session_sync,
            on_result=lambda k, l, img, c, g=gen: self.root.after(
                0, self._on_sim_result, g, k, img),
            on_complete=lambda g=gen: self.root.after(
                0, self._on_sim_complete, g),
            on_error=lambda k, err, g=gen: self.root.after(
                0, self._on_sim_error, g, k, err),
        )

    def _discard_auto_dialog(self):
        """Close the current auto dialog without invoking select/cancel callbacks."""
        dlg = self._auto_dialog
        if dlg is None:
            return
        self._auto_dialog = None
        try:
            dlg._closed = True
            dlg.top.destroy()
        except Exception:
            pass

    def _on_sim_result(self, gen, key, rgba_image):
        if gen != self._sim_gen or self._auto_dialog is None:
            return
        self._auto_dialog.show_result(key, rgba_image)

    def _on_sim_error(self, gen, key, err):
        if gen != self._sim_gen or self._auto_dialog is None:
            return
        self._auto_dialog.show_error(key, err)

    def _on_sim_complete(self, gen):
        if gen != self._sim_gen:
            return
        if self._auto_dialog is not None:
            self._auto_dialog.set_complete()
        self._set_status("후보를 선택하세요.")

    def _on_auto_pick(self, combo):
        """User clicked a thumbnail — sync UI, apply to full-res. Dialog stays open."""
        self._apply_combo_to_ui(combo)
        if combo["model"] != self.remover.current_model:
            self._pending_reprocess = True
            self._load_model(combo["model"])
        else:
            self._run_removal(self._process_image)

    def _on_auto_close(self, had_pick):
        """Dialog was dismissed. If nothing was ever picked, run manual fallback."""
        self._auto_dialog = None
        if not had_pick:
            self._run_removal(self._process_image)

    def _on_bg_color_change(self, color):
        """Forward main-window BG color changes to the open auto dialog."""
        if self._auto_dialog is not None:
            self._auto_dialog.update_bg_color(color)

    def _apply_combo_to_ui(self, combo):
        """Reflect a selected combo in the pipeline widgets without triggering traces."""
        self._suppress_trace = True
        try:
            self._postmask_var.set(combo["post_process"])
            self._alpha_clean_var.set(combo["alpha_clean"])
            self._alpha_matting_var.set(combo["alpha_matting"])
            # Update combobox display
            for idx, (name, _label) in enumerate(AVAILABLE_MODELS):
                if name == combo["model"]:
                    self._model_combo.current(idx)
                    self._model_var.set(name)
                    break
        finally:
            self._suppress_trace = False

    def _run_removal(self, img):
        self._processing = True
        self._raw_result = None
        self.result_panel.start_spinner()
        self._set_status("Processing...")

        self.remover.remove_async(
            img,
            on_success=lambda result: self.root.after(0, self._on_done, result),
            on_error=lambda err: self.root.after(0, self._on_error, err),
            alpha_clean=False,
            alpha_matting=self._alpha_matting_var.get(),
            post_process_mask=self._postmask_var.get(),
        )

    def _on_done(self, result_image):
        self._raw_result = result_image
        self._apply_final_and_show()
        self._set_status("Done!  Drag another image or click Save.")
        self._processing = False

    def _on_error(self, err):
        self.result_panel.stop_spinner()
        self._set_status(f"Error: {err}")
        self._processing = False
