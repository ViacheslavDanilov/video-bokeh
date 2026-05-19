"""Deterministic textured background for isolated object depth inference."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter


def make_textured_bg(size: int, seed: int = 0) -> np.ndarray:
    """Return a low-frequency RGB noise texture centered on mid-gray."""
    rng = np.random.default_rng(seed)
    out = np.zeros((size, size, 3), dtype=np.float32)

    for sigma, weight in ((size / 8.0, 0.66), (size / 32.0, 0.34)):
        noise = rng.standard_normal((size, size, 3)).astype(np.float32)
        for channel in range(3):
            noise[..., channel] = gaussian_filter(noise[..., channel], sigma=sigma)
            std = noise[..., channel].std() or 1.0
            noise[..., channel] = noise[..., channel] / std
        out += weight * noise

    p_lo, p_hi = np.percentile(out, [1.0, 99.0])
    center = (p_lo + p_hi) / 2.0
    scale = max(float(p_hi - center), float(center - p_lo), 1e-6)
    out = 128.0 + 30.0 * ((out - center) / scale)
    return np.clip(out, 98, 158).astype(np.uint8)
