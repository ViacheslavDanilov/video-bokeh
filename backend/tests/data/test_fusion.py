from __future__ import annotations

import numpy as np

from video_bokeh.core._fusion import (
    assign_depth_slots,
    bg_normalize,
    place_in_band,
)


def test_bg_normalize_maps_into_bg_band() -> None:
    disp = np.array([[0.0, 0.5], [1.0, 0.25]], dtype=np.float32)
    out = bg_normalize(disp, bg_band_top=0.05)

    assert out.min() >= 0.0 - 1e-6
    assert out.max() <= 0.05 + 1e-6


def test_place_in_band_stretches_into_explicit_bounds() -> None:
    disp = np.array([[0.0, 1.0], [0.5, 0.5]], dtype=np.float32)
    alpha = np.ones_like(disp)
    out = place_in_band(disp, alpha, band_lo=0.30, band_hi=0.40)
    assert out[alpha > 0].min() >= 0.30 - 1e-6
    assert out.max() <= 0.40 + 1e-6


def test_place_in_band_fills_outside_alpha_with_band_lo() -> None:
    disp = np.array([[0.0, 1.0], [0.5, 0.5]], dtype=np.float32)
    alpha = np.array([[1.0, 1.0], [0.0, 0.0]], dtype=np.float32)
    out = place_in_band(disp, alpha, band_lo=0.20, band_hi=0.30)
    assert np.allclose(out[1, :], 0.20)


def test_assign_depth_slots_are_disjoint_and_ordered() -> None:
    slots = assign_depth_slots(n_objects=3, bg_band_top=0.05, gap=0.02)
    assert len(slots) == 3
    for lo, hi in slots:
        assert 0.05 <= lo < hi <= 1.0
    # Disjoint with a gap between consecutive slots.
    for (_, hi_a), (lo_b, _) in zip(slots, slots[1:], strict=False):
        assert hi_a + 0.02 - 1e-6 <= lo_b
