"""Enlarge a per-object disparity to a full-frame map (Valery's edge refinement).

Ported from the standalone ``edge_refinement_v2.py``: erode the alpha to a
trusted core, copy each pixel's disparity from its nearest trusted pixel, then
Gaussian-blur the propagated region to smooth the nearest-pixel discontinuities.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import binary_erosion, distance_transform_edt, gaussian_filter

_BLUR_SIGMA = 3.0


def trusted_core(
    alpha: np.ndarray,
    disparity: np.ndarray,
    nb_pixels_remove: int = 5,
    threshold: float = 0.04,
    low_pct: float = 0.0,
) -> np.ndarray:
    """Boolean (H, W) mask of pixels whose disparity we trust.

    Start from ``alpha >= threshold``, erode ``nb_pixels_remove`` border pixels,
    keep only finite values, and (when ``low_pct > 0``) drop pixels below the
    ``low_pct`` percentile of the eroded-core disparity -- these look like
    depth-model holes and would otherwise propagate outward.
    """
    a = np.asarray(alpha, dtype=np.float32)
    disp = np.asarray(disparity, dtype=np.float32)
    mask = a >= threshold
    eroded = binary_erosion(mask, iterations=nb_pixels_remove)
    valid = eroded & np.isfinite(disp)
    if low_pct > 0.0 and valid.any():
        floor = float(np.percentile(disp[valid], low_pct))
        valid &= disp >= floor
    return valid


def propagate_disparity(
    disparity: np.ndarray,
    alpha: np.ndarray,
    nb_pixels_remove: int = 5,
    threshold: float = 0.04,
    blur_sigma: float = _BLUR_SIGMA,
    low_pct: float = 0.0,
) -> np.ndarray:
    """Propagate in-object disparity across the whole frame.

    ``low_pct`` (default 0 = off, preserving the original behaviour) drops
    low-percentile outliers from the trusted core before propagation; see
    ``trusted_core``.
    """
    disp = np.asarray(disparity, dtype=np.float32)
    a = np.asarray(alpha, dtype=np.float32)
    if disp.shape != a.shape:
        raise ValueError(f"disparity {disp.shape} and alpha {a.shape} shape mismatch")

    valid = trusted_core(a, disp, nb_pixels_remove, threshold, low_pct)
    if not valid.any():
        return disp.copy()

    _, indices = distance_transform_edt(~valid, return_indices=True)
    propagated = disp[indices[0], indices[1]].astype(np.float32)

    blurred = gaussian_filter(propagated, blur_sigma)
    propagated[~valid] = blurred[~valid]
    return propagated
