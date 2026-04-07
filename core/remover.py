import os
import sys
import threading
import io
import numpy as np
from PIL import Image
from rembg import new_session, remove

AVAILABLE_MODELS = [
    ("isnet-general-use", "ISNet (high detail)"),
    ("u2net", "U2Net (general)"),
    ("u2net_human_seg", "U2Net (portrait)"),
]


def _get_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _clean_alpha(image, threshold=200):
    """Remove semi-transparent halo by sharpening the alpha channel."""
    arr = np.array(image)
    alpha = arr[:, :, 3].astype(np.float32)
    # Remap: below threshold→0, above→255, smooth ramp in between
    lo, hi = 80, threshold
    alpha = np.clip((alpha - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
    arr[:, :, 3] = alpha
    return Image.fromarray(arr)


class BackgroundRemover:
    def __init__(self):
        self._sessions = {}  # model_name -> session
        self.current_model = AVAILABLE_MODELS[0][0]
        self.mode = None

    def init_session(self, model_name, on_ready, on_error=None):
        """Load a model session in a background thread."""

        def task():
            try:
                if model_name not in self._sessions:
                    local_model = os.path.join(
                        _get_base_dir(), "models", f"{model_name}.onnx"
                    )
                    if os.path.exists(local_model):
                        session = new_session(
                            model_name,
                            providers=["CPUExecutionProvider"],
                            model_path=local_model,
                        )
                        self.mode = "offline"
                    else:
                        session = new_session(model_name)
                        self.mode = "online"
                    self._sessions[model_name] = session

                self.current_model = model_name
                on_ready(self.mode, model_name)
            except Exception as e:
                if on_error:
                    on_error(str(e))

        threading.Thread(target=task, daemon=True).start()

    @property
    def session(self):
        return self._sessions.get(self.current_model)

    def remove_async(
        self, pil_image: Image.Image, on_success, on_error,
        alpha_clean=True, alpha_matting=False,
    ):
        """Run background removal in a worker thread."""

        def task():
            try:
                buf = io.BytesIO()
                pil_image.save(buf, format="PNG")
                kwargs = dict(
                    session=self.session,
                    post_process_mask=True,
                )
                if alpha_matting:
                    kwargs.update(
                        alpha_matting=True,
                        alpha_matting_foreground_threshold=230,
                        alpha_matting_background_threshold=20,
                        alpha_matting_erode_size=7,
                    )
                result_bytes = remove(buf.getvalue(), **kwargs)
                result = Image.open(io.BytesIO(result_bytes)).convert("RGBA")
                if alpha_clean:
                    result = _clean_alpha(result)
                on_success(result)
            except Exception as e:
                on_error(str(e))

        threading.Thread(target=task, daemon=True).start()
