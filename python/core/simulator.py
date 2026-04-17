"""Run pipeline combinations on a downscaled image for preview."""
import io
import threading
from PIL import Image
from rembg import remove

from core.remover import _clean_alpha


def simulate_async(
    pil_image: Image.Image,
    candidates: list,
    ensure_session,
    on_result,
    on_complete,
    on_error,
    preview_size: int = 512,
):
    """Run each candidate sequentially on a downscaled copy.

    Args:
        pil_image: full-resolution source.
        candidates: list of dicts with model/post_process/alpha_clean/alpha_matting/key/label.
        ensure_session: callable(model_name) -> session. May block to load.
        on_result: callable(key, label, rgba_thumbnail, combo_dict).
        on_complete: callable().
        on_error: callable(key, err_str).
    """

    def task():
        small = pil_image.copy()
        small.thumbnail((preview_size, preview_size), Image.LANCZOS)
        rgb = small.convert("RGB")
        buf = io.BytesIO()
        rgb.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        for combo in candidates:
            try:
                session = ensure_session(combo["model"])
                kwargs = dict(
                    session=session,
                    post_process_mask=combo["post_process"],
                )
                if combo["alpha_matting"]:
                    kwargs.update(
                        alpha_matting=True,
                        alpha_matting_foreground_threshold=230,
                        alpha_matting_background_threshold=20,
                        alpha_matting_erode_size=7,
                    )
                out = remove(png_bytes, **kwargs)
                result = Image.open(io.BytesIO(out)).convert("RGBA")
                if combo["alpha_clean"]:
                    result = _clean_alpha(result)
                on_result(combo["key"], combo["label"], result, combo)
            except Exception as e:
                on_error(combo["key"], str(e))

        on_complete()

    threading.Thread(target=task, daemon=True).start()
