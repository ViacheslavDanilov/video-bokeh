"""Per-object disparity band normalization and alpha-layer compositing."""

from __future__ import annotations

import numpy as np

_P_LO = 1.0
_P_HI = 99.0
_DEGENERATE_BAND_FRAC = 0.25


def place_in_band(
    disp: np.ndarray,
    alpha: np.ndarray,
    band_lo: float,
    band_hi: float,
    band_width: float = 0.10,
) -> np.ndarray:
    """Percentile-stretch in-object disparity into the explicit [lo, hi] band.

    Pixels outside ``alpha > 0`` are set to ``band_lo``. ``band_width`` is only
    used to decide when a band is too degenerate to stretch into, in which case
    the whole object falls back to the band midpoint.
    """
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


def assign_depth_slots(
    n_objects: int,
    bg_band_top: float = 0.05,
    gap: float = 0.02,
) -> list[tuple[float, float]]:
    """Partition the disparity axis above the background into disjoint slots.

    Returns ``n_objects`` (lo, hi) bands in paint order (index 0 = farthest /
    drawn first, last = nearest / drawn last). Slots are separated by ``gap`` so
    that bounded zoom-scaling can never make two objects share a disparity.
    """
    if n_objects <= 0:
        return []
    usable = 1.0 - bg_band_top - gap * (n_objects - 1)
    if usable <= 0.0:
        raise ValueError(
            f"no room for {n_objects} slots above bg_band_top={bg_band_top} "
            f"with gap={gap}",
        )
    width = usable / n_objects
    slots: list[tuple[float, float]] = []
    cursor = bg_band_top
    for _ in range(n_objects):
        lo = cursor
        hi = lo + width
        slots.append((lo, hi))
        cursor = hi + gap
    return slots
