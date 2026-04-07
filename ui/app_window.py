import os
import tkinter as tk
from tkinter import ttk
from PIL import Image

from ui.drop_zone import DropZone, VALID_EXTENSIONS
from ui.result_panel import ResultPanel
from ui.edit_panel import EditPanel
from ui.tooltip import ToolTip
from core.remover import BackgroundRemover, AVAILABLE_MODELS, _clean_alpha


class AppWindow:
    """Main application controller that wires up all UI components."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.configure(bg="#1e1e1e")
        self.remover = BackgroundRemover()
        self._processing = False
        self._last_filepath = None
        self._source_image = None
        self._raw_result = None

        # ===== main view widgets =====
        self._main_widgets = []

        # -- status bar (pack BOTTOM first — always visible) --
        self._status_var = tk.StringVar(value="Loading model...")
        status_frame = tk.Frame(root, bg="#181818")
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self._status_bar = tk.Label(
            status_frame, textvariable=self._status_var,
            bg="#181818", fg="#888888", anchor=tk.W,
            font=("Segoe UI", 9), padx=8, pady=4,
        )
        self._status_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            status_frame, text="v1.0", bg="#181818", fg="#555555",
            font=("Segoe UI", 8), padx=8, pady=4,
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
        self.result_panel = ResultPanel(root, on_edit=self._enter_edit)
        self.result_panel.pack(side=tk.TOP, padx=20, pady=(0, 4),
                               fill=tk.BOTH, expand=True)
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
        tk.Label(
            frame, text="Pipeline:", bg="#1e1e1e", fg="#666666",
            font=("Segoe UI", 8),
        ).pack(side=tk.LEFT, padx=(0, 6))

        # Model selector + info
        info1 = tk.Label(frame, text="\u24d8", bg="#1e1e1e", fg="#00d4aa",
                         font=("Segoe UI", 11), cursor="hand2")
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
                 font=("Segoe UI", 7)).pack(side=tk.LEFT, padx=(0, 6))

        # Alpha Clean + info
        info2 = tk.Label(frame, text="\u24d8", bg="#1e1e1e", fg="#00d4aa",
                         font=("Segoe UI", 11), cursor="hand2")
        info2.pack(side=tk.LEFT)
        ToolTip(info2,
                "Alpha Clean\n"
                "\ubc18\ud22c\uba85 \ud5e4\uc77c\ub85c(\ubc88\uc9d0) \uc81c\uac70\n"
                "alpha < 80 \u2192 \uc644\uc804 \ud22c\uba85\n"
                "alpha > 200 \u2192 \uc644\uc804 \ubd88\ud22c\uba85")
        self._alpha_clean_var = tk.BooleanVar(value=True)
        self._alpha_clean_var.trace_add("write", self._on_alpha_clean_toggle)
        tk.Checkbutton(
            frame, text="Alpha Clean", variable=self._alpha_clean_var,
            bg="#1e1e1e", fg="#e0e0e0", selectcolor="#2a2a2a",
            activebackground="#1e1e1e", activeforeground="#00d4aa",
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=(0, 6))

        tk.Label(frame, text="\u25b6", bg="#1e1e1e", fg="#555555",
                 font=("Segoe UI", 7)).pack(side=tk.LEFT, padx=(0, 6))

        # Alpha Matting + info
        info3 = tk.Label(frame, text="\u24d8", bg="#1e1e1e", fg="#00d4aa",
                         font=("Segoe UI", 11), cursor="hand2")
        info3.pack(side=tk.LEFT)
        ToolTip(info3,
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
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT)

    # ===== view switching =====

    def _enter_edit(self, result_image, format_val, stem):
        for w in self._main_widgets:
            w.pack_forget()
        self.edit_panel.pack(side=tk.TOP, padx=10, pady=(6, 0),
                             fill=tk.BOTH, expand=True,
                             before=self._status_bar)
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
        if self._raw_result is None:
            return
        self._apply_final_and_show()

    def _on_reprocess_toggle(self, *_args):
        if self._source_image is not None and not self._processing:
            self._run_removal(self._source_image)

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
        if getattr(self, "_pending_reprocess", False) and self._source_image is not None:
            self._pending_reprocess = False
            self.root.after(0, self._run_removal, self._source_image)

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
            img = Image.open(filepath).convert("RGB")
        except Exception as e:
            self._set_status(f"Cannot open image: {e}")
            return

        self._source_image = img
        self.result_panel.show_before(img)
        self._run_removal(img)

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
