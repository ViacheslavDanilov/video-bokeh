from __future__ import annotations

import numpy as np
import pytest

from data._fusion import band_normalize, bg_normalize, composite_layers


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
