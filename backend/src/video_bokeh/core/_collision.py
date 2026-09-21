"""Per-frame 3D-occupancy collision test for object pairs.

Two objects collide at a frame only when their alpha masks overlap AND their
active disparity intervals overlap (within a safety margin) on those pixels. A
2D overlap with clearly separated depth is allowed -- one object is simply in
front of the other.
"""

from __future__ import annotations

import numpy as np


def pair_collides(
    alpha_i: np.ndarray,
    interval_i: tuple[float, float],
    alpha_j: np.ndarray,
    interval_j: tuple[float, float],
    margin: float = 0.02,
    alpha_threshold: float = 0.5,
) -> bool:
    """True if the two objects occupy the same pixels at overlapping depth."""
    overlap = (alpha_i > alpha_threshold) & (alpha_j > alpha_threshold)
    if not overlap.any():
        return False
    lo_i, hi_i = interval_i
    lo_j, hi_j = interval_j
    if hi_i + margin < lo_j:  # i strictly behind j
        return False
    if hi_j + margin < lo_i:  # j strictly behind i
        return False
    return True
