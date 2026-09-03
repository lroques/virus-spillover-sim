from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image
from scipy.ndimage import binary_erosion

from .model import DEFAULTS, load_maps, convolved_reservoir, spatial_intensity


def _rgba_from_values(values: np.ndarray, mode: str, vmin: float | None = None, vmax: float | None = None) -> np.ndarray:
    maps = load_maps()
    mask = maps.mask & np.isfinite(values)
    valid = values[mask]

    if valid.size == 0:
        return np.zeros((*values.shape, 4), dtype=np.uint8)

    if vmin is None:
        vmin = float(np.nanmin(valid))
    if vmax is None:
        vmax = float(np.nanmax(valid))
    if vmax <= vmin:
        vmax = vmin + 1.0

    norm = np.zeros_like(values, dtype=float)
    if mode == "log":
        safe = np.maximum(values, max(vmin, 1e-300))
        lo = np.log10(max(vmin, 1e-300))
        hi = np.log10(max(vmax, vmin * 1.000001))
        norm = (np.log10(safe) - lo) / (hi - lo)
    else:
        norm = (values - vmin) / (vmax - vmin)
    norm = np.where(mask, np.clip(norm, 0.0, 1.0), 0.0)

    idx = np.rint(norm * 255).astype(np.int16)
    lut = np.clip(maps.viridis * 255.0, 0, 255).astype(np.uint8)
    rgb = lut[np.clip(idx, 0, 255)]

    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    rgba[..., :3] = rgb
    rgba[..., 3] = np.where(mask, 238, 0).astype(np.uint8)

    # Add a high-contrast country outline derived from the common mask.
    edge = maps.mask & ~binary_erosion(maps.mask, structure=np.ones((3, 3), dtype=bool))
    rgba[edge, :3] = np.array([20, 28, 45], dtype=np.uint8)
    rgba[edge, 3] = 255
    return rgba


def render_layer_png(
    layer: str,
    D: float = DEFAULTS["D"],
    beta0: float = DEFAULTS["beta0"],
    beta1: float = DEFAULTS["beta1"],
) -> tuple[bytes, dict]:
    maps = load_maps()
    if layer == "Ks":
        values = maps.Ks
        finite = values[np.isfinite(values)]
        vmin = float(np.nanmin(finite))
        vmax = float(np.nanmax(finite))
        mode = "log"
        label = "K_s human density"
    elif layer == "Kr":
        values = maps.Kr
        finite = values[np.isfinite(values)]
        vmin = float(np.nanmin(finite))
        vmax = float(np.nanmax(finite))
        mode = "linear"
        label = "K_r bat reservoir density"
    elif layer == "alpha":
        values = maps.alpha
        finite = values[np.isfinite(values)]
        vmin = float(np.nanmin(finite))
        vmax = float(np.nanmax(finite))
        mode = "linear"
        label = "Date-palm consumption covariate alpha"
    elif layer == "reservoir_smoothed":
        values = convolved_reservoir(D, maps)
        finite = values[np.isfinite(values)]
        vmin = float(np.nanmin(finite))
        vmax = float(np.nanmax(finite))
        mode = "linear"
        label = "J_D * K_r"
    elif layer == "spillover":
        values, _ = spatial_intensity(D, beta0, beta1, maps)
        finite = values[np.isfinite(values) & (values > 0)]
        if finite.size:
            vmin, vmax = [float(x) for x in np.quantile(finite, [0.02, 0.995])]
        else:
            vmin, vmax = 0.0, 1.0
        mode = "log"
        label = "Integrated spillover infection intensity density"
    else:
        raise KeyError(layer)

    rgba = _rgba_from_values(values, mode, vmin, vmax)
    # Data arrays are stored south-to-north; PNG raster rows run top-to-bottom.
    rgba = rgba[::-1, :, :]
    image = Image.fromarray(rgba, mode="RGBA")
    buf = BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), {"min": vmin, "max": vmax, "mode": mode, "label": label}
