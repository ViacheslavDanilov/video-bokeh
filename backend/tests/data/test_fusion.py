from __future__ import annotations

import numpy as np
import pytest

from data._fusion import (
    assign_depth_slots,
    band_normalize,
    bg_normalize,
    composite_layers,
    place_in_band,
    scaled_band,
)


def test_band_normalize_inverts_renderer_depth_semantic() -> None:
    disp = np.array([[0.0, 1.0], [0.5, 0.5]], dtype=np.float32)
    alpha = np.ones_like(disp)

    near = band_normalize(disp, alpha, object_depth=0.0)
    far = band_normalize(disp, alpha, object_depth=1.0)

    assert near.max() > far.max()


def test_band_normalize_respects_band_clip() -> None:
    disp = np.array([[0.0, 1.0], [0.5, 0.5]], dtype=np.float32)
    alpha = np.ones_like(disp)
    out = band_normalize(disp, alpha, object_depth=0.5, band_width=0.1)

    assert out.max() <= 0.55 + 1e-6
    assert out[alpha > 0].min() >= 0.45 - 1e-6


def test_band_normalize_handles_constant_disparity_via_fallback() -> None:
    disp = np.full((4, 4), 0.7, dtype=np.float32)
    alpha = np.ones_like(disp)
    out = band_normalize(disp, alpha, object_depth=0.5, band_width=0.1)

    assert np.allclose(out, 0.5)


def test_band_normalize_floors_degenerate_band() -> None:
    disp = np.array([[0.0, 1.0], [0.5, 0.5]], dtype=np.float32)
    alpha = np.ones_like(disp)
    out = band_normalize(
        disp,
        alpha,
        object_depth=1.0,
        band_width=0.1,
        bg_band_top=0.05,
    )

    assert np.allclose(out, 0.05)


def test_band_normalize_outlier_robustness() -> None:
    disp = np.zeros((100, 100), dtype=np.float32)
    disp[0, 0] = 1000.0
    alpha = np.ones_like(disp)
    out = band_normalize(disp, alpha, object_depth=0.5, band_width=0.1)

    assert np.allclose(out, 0.5)


def test_bg_normalize_maps_into_bg_band() -> None:
    disp = np.array([[0.0, 0.5], [1.0, 0.25]], dtype=np.float32)
    out = bg_normalize(disp, bg_band_top=0.05)

    assert out.min() >= 0.0 - 1e-6
    assert out.max() <= 0.05 + 1e-6


def test_composite_layers_paints_in_paint_order() -> None:
    bg = np.full((4, 4), 0.02, dtype=np.float32)
    obj0 = np.full((4, 4), 0.30, dtype=np.float32)
    obj1 = np.full((4, 4), 0.70, dtype=np.float32)
    alpha0 = np.ones((4, 4), dtype=np.float32)
    alpha1 = np.ones((4, 4), dtype=np.float32)

    out = composite_layers(bg, [obj0, obj1], [alpha0, alpha1])

    assert np.allclose(out, 0.70)


def test_composite_layers_respects_alpha_blend() -> None:
    bg = np.full((4, 4), 0.0, dtype=np.float32)
    obj = np.full((4, 4), 1.0, dtype=np.float32)
    alpha = np.full((4, 4), 0.5, dtype=np.float32)

    out = composite_layers(bg, [obj], [alpha])

    assert np.allclose(out, 0.5)


def test_composite_layers_input_validation() -> None:
    bg = np.zeros((2, 2), dtype=np.float32)
    with pytest.raises(ValueError):
        composite_layers(bg, [np.zeros((2, 2), dtype=np.float32)], [])


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


def test_scaled_band_moves_active_band_toward_near_end_on_zoom_in() -> None:
    # Narrow active band inside a broad envelope.
    base = scaled_band(0.20, 0.80, active_width=0.10, scale_t=1.0, scale_ref=1.0)
    zoomed = scaled_band(0.20, 0.80, active_width=0.10, scale_t=2.0, scale_ref=1.0)
    # Zoom in => closer => higher disparity: the band must actually move up.
    assert zoomed[0] > base[0] + 1e-3
    assert zoomed[1] > base[1] + 1e-3
    # Width is preserved at active_width regardless of scale.
    assert abs((base[1] - base[0]) - 0.10) < 1e-6
    assert abs((zoomed[1] - zoomed[0]) - 0.10) < 1e-6


def test_scaled_band_centers_at_envelope_centre_at_reference_scale() -> None:
    lo, hi = scaled_band(0.20, 0.80, active_width=0.10, scale_t=1.0, scale_ref=1.0)
    assert abs((lo + hi) / 2.0 - 0.50) < 1e-6


def test_scaled_band_clamps_active_band_inside_envelope() -> None:
    lo, hi = scaled_band(0.20, 0.80, active_width=0.10, scale_t=100.0, scale_ref=1.0)
    assert lo >= 0.20 - 1e-6
    assert hi <= 0.80 + 1e-6
    assert abs((hi - lo) - 0.10) < 1e-6


def test_scaled_band_active_width_capped_at_envelope_width() -> None:
    # If active_width exceeds the envelope, it is capped to the envelope width.
    lo, hi = scaled_band(0.40, 0.50, active_width=0.30, scale_t=1.0, scale_ref=1.0)
    assert lo >= 0.40 - 1e-6
    assert hi <= 0.50 + 1e-6
