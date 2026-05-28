"""Per-object disparity band normalization and alpha-layer compositing."""

from __future__ import annotations

import numpy as np

_P_LO = 1.0
_P_HI = 99.0
_DEGENERATE_BAND_FRAC = 0.25


def _band_for(
    object_depth: float,
    band_width: float,
    bg_band_top: float,
) -> tuple[float, float]:
    """Map renderer depth (larger = farther) to disparity band (larger = closer)."""
    anchor = 1.0 - float(object_depth)
    lo = max(bg_band_top, anchor - band_width / 2.0)
    hi = min(1.0, anchor + band_width / 2.0)
    return lo, hi


def band_normalize(
    disp: np.ndarray,
    alpha: np.ndarray,
    object_depth: float,
    band_width: float = 0.10,
    bg_band_top: float = 0.05,
) -> np.ndarray:
    """Rescale in-object disparity into that object's global-axis band."""
    band_lo, band_hi = _band_for(object_depth, band_width, bg_band_top)
    out = np.full_like(disp, band_lo, dtype=np.float32)
    mask = alpha > 0
    region = disp[mask]
    if region.size == 0:
        return out

    p_lo, p_hi = np.percentile(region, [_P_LO, _P_HI])
    src_range = float(p_hi - p_lo)
    band_size = band_hi - band_lo
    band_mid = (band_lo + band_hi) / 2.0

    if band_size < _DEGENERATE_BAND_FRAC * band_width or src_range <= 1e-8:
        out[mask] = band_mid
        return out

    clipped = np.clip(disp, p_lo, p_hi)
    scaled = (clipped - p_lo) / src_range
    rescaled = band_lo + scaled * band_size
    out[mask] = rescaled[mask]
    return out


def bg_normalize(disp: np.ndarray, bg_band_top: float = 0.05) -> np.ndarray:
    """Rescale full-frame background disparity into [0, bg_band_top]."""
    p_lo, p_hi = np.percentile(disp, [_P_LO, _P_HI])
    src_range = float(p_hi - p_lo)
    if src_range <= 1e-8:
        return np.full_like(disp, bg_band_top / 2.0, dtype=np.float32)

    clipped = np.clip(disp, p_lo, p_hi)
    scaled = (clipped - p_lo) / src_range
    return (scaled * bg_band_top).astype(np.float32)


def composite_layers(
    bg_norm: np.ndarray,
    obj_norms: list[np.ndarray],
    alphas: list[np.ndarray],
) -> np.ndarray:
    """Composite normalized object disparities over the background in paint order."""
    if len(obj_norms) != len(alphas):
        raise ValueError(
            f"obj_norms ({len(obj_norms)}) and alphas ({len(alphas)}) length mismatch",
        )

    final = bg_norm.astype(np.float32, copy=True)
    for disp, alpha in zip(obj_norms, alphas, strict=True):
        final = alpha * disp + (1.0 - alpha) * final
    return final.astype(np.float32, copy=False)
