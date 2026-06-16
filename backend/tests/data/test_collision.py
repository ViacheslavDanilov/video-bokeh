from __future__ import annotations

import numpy as np

from data._collision import pair_collides


def _mask(box):
    m = np.zeros((32, 32), dtype=bool)
    r0, r1, c0, c1 = box
    m[r0:r1, c0:c1] = True
    return m


def test_no_overlap_is_valid() -> None:
    a = _mask((0, 10, 0, 10))
    b = _mask((20, 30, 20, 30))
    assert not pair_collides(a, (0.5, 0.6), b, (0.55, 0.65), margin=0.02)


def test_overlap_with_separated_depth_is_valid() -> None:
    a = _mask((0, 16, 0, 16))
    b = _mask((8, 24, 8, 24))  # overlaps a
    # depth intervals separated by more than the margin
    assert not pair_collides(a, (0.20, 0.30), b, (0.60, 0.70), margin=0.02)


def test_overlap_with_overlapping_depth_collides() -> None:
    a = _mask((0, 16, 0, 16))
    b = _mask((8, 24, 8, 24))
    assert pair_collides(a, (0.30, 0.45), b, (0.40, 0.55), margin=0.02)
