"""Enlarge a per-object disparity to a full-frame map (Valery's edge refinement).

Ported from the standalone ``edge_refinement_v2.py``: erode the alpha to a
trusted core, copy each pixel's disparity from its nearest trusted pixel, then
Gaussian-blur the propagated region to smooth the nearest-pixel discontinuities.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import binary_erosion, distance_transform_edt, gaussian_filter

_BLUR_SIGMA = 3.0


def propagate_disparity(
    disparity: np.ndarray,
    alpha: np.ndarray,
    nb_pixels_remove: int = 5,
    threshold: float = 0.04,
    blur_sigma: float = _BLUR_SIGMA,
) -> np.ndarray:
    """Propagate in-object disparity across the whole frame.

    ``disparity`` and ``alpha`` are (H, W) float arrays. ``alpha`` is compared
    against ``threshold`` (same units as alpha) to form the binary object mask;
    ``nb_pixels_remove`` border pixels are eroded away as unreliable. Returns a
    (H, W) float32 map: the trusted core keeps its sharp disparity, every other
    pixel takes its nearest trusted value, and the propagated region is blurred.
    """
    disp = np.asarray(disparity, dtype=np.float32)
    a = np.asarray(alpha, dtype=np.float32)
    if disp.shape != a.shape:
        raise ValueError(f"disparity {disp.shape} and alpha {a.shape} shape mismatch")

    mask = a >= threshold
    eroded = binary_erosion(mask, iterations=nb_pixels_remove)
    valid = eroded.astype(bool)
    if not valid.any():
        # No trusted core survived erosion; fall back to the raw map.
        return disp.copy()

    # For each pixel, indices of the nearest trusted (valid) pixel.
    _, indices = distance_transform_edt(~valid, return_indices=True)
    propagated = disp[indices[0], indices[1]].astype(np.float32)

    blurred = gaussian_filter(propagated, blur_sigma)
    propagated[~valid] = blurred[~valid]
    return propagated
