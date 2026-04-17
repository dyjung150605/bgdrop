"""Auto combination selection.

Analyzes an image with lightweight PIL + numpy heuristics and picks a
shortlist of pipeline combinations to simulate.
"""
import numpy as np
from PIL import Image, ImageFilter


# Pipeline combination presets.
# Each combo maps to one full pipeline configuration.
COMBINATIONS = {
    "isnet_balanced": {
        "model": "isnet-general-use",
        "post_process": True,
        "alpha_clean": True,
        "alpha_matting": False,
        "label": "스탠다드",
    },
    "isnet_matting": {
        "model": "isnet-general-use",
        "post_process": True,
        "alpha_clean": True,
        "alpha_matting": True,
        "label": "정밀 경계",
    },
    "human_balanced": {
        "model": "u2net_human_seg",
        "post_process": True,
        "alpha_clean": True,
        "alpha_matting": False,
        "label": "인물",
    },
    "human_matting": {
        "model": "u2net_human_seg",
        "post_process": True,
        "alpha_clean": True,
        "alpha_matting": True,
        "label": "인물 정밀",
    },
    "u2net_fast": {
        "model": "u2net",
        "post_process": True,
        "alpha_clean": True,
        "alpha_matting": False,
        "label": "쾌속",
    },
    "isnet_soft": {
        "model": "isnet-general-use",
        "post_process": False,
        "alpha_clean": True,
        "alpha_matting": False,
        "label": "소프트",
    },
}


def analyze_image(pil_image: Image.Image) -> dict:
    """Return heuristic features used to pick candidate combinations."""
    img = pil_image.copy()
    img.thumbnail((256, 256), Image.LANCZOS)

    # Edge density via FIND_EDGES
    edges = np.array(img.convert("L").filter(ImageFilter.FIND_EDGES))
    edge_density = float((edges > 50).mean())

    # Skin-tone heuristic (Kovac rule on RGB)
    rgb = np.array(img.convert("RGB"))
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    max_c = rgb.max(axis=2)
    min_c = rgb.min(axis=2)
    skin_mask = (
        (r > 95) & (g > 40) & (b > 20)
        & ((max_c - min_c) > 15)
        & (np.abs(r.astype(int) - g.astype(int)) > 15)
        & (r > g) & (r > b)
    )
    skin_ratio = float(skin_mask.mean())

    w, h = pil_image.size
    aspect_ratio = w / h if h else 1.0

    return {
        "edge_density": edge_density,
        "skin_ratio": skin_ratio,
        "aspect_ratio": aspect_ratio,
        "likely_human": skin_ratio > 0.04,
        "complex_edges": edge_density > 0.10,
    }


def pick_candidates(features: dict, limit: int = 4) -> list:
    """Return up to `limit` candidate combos as list of dicts.

    Each dict has keys: key, model, post_process, alpha_clean, alpha_matting, label.
    """
    order = []
    if features["likely_human"]:
        order.append("human_balanced")
        if features["complex_edges"]:
            order.append("human_matting")
            order.append("isnet_matting")
        else:
            order.append("isnet_balanced")
        order.append("u2net_fast")
    else:
        order.append("isnet_balanced")
        if features["complex_edges"]:
            order.append("isnet_matting")
        order.append("u2net_fast")
        order.append("isnet_soft")

    # Dedupe preserving order
    seen = []
    for k in order:
        if k not in seen:
            seen.append(k)
        if len(seen) >= limit:
            break

    return [{"key": k, **COMBINATIONS[k]} for k in seen]
