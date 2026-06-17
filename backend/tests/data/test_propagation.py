from __future__ import annotations

import numpy as np

from data._propagation import propagate_disparity, trusted_core


def test_fills_full_frame_from_object_core() -> None:
    disp = np.zeros((20, 20), dtype=np.float32)
    disp[6:14, 6:14] = 0.8
    alpha = np.zeros((20, 20), dtype=np.float32)
    alpha[6:14, 6:14] = 1.0

    out = propagate_disparity(disp, alpha, nb_pixels_remove=2, threshold=0.5)

    assert out.shape == (20, 20)
    # Every pixel got a value propagated from the trusted core (~0.8).
    assert out.min() > 0.0
    assert abs(float(out.mean()) - 0.8) < 0.1


def test_blur_smooths_propagated_region_only() -> None:
    disp = np.zeros((30, 30), dtype=np.float32)
    disp[10:20, 10:20] = 1.0
    alpha = np.zeros((30, 30), dtype=np.float32)
    alpha[10:20, 10:20] = 1.0

    out = propagate_disparity(disp, alpha, nb_pixels_remove=3, threshold=0.5)
    # Trusted core (after erosion) keeps its sharp value; corner is propagated.
    assert abs(float(out[14, 14]) - 1.0) < 1e-3
    assert float(out[0, 0]) > 0.0


def test_threshold_is_fraction_of_alpha_max() -> None:
    # alpha given in [0,1]; threshold 0.5 keeps the >=0.5 region.
    disp = np.full((10, 10), 0.5, dtype=np.float32)
    alpha = np.full((10, 10), 0.6, dtype=np.float32)
    out = propagate_disparity(disp, alpha, nb_pixels_remove=1, threshold=0.5)
    assert np.allclose(out, 0.5, atol=1e-3)


def test_trusted_core_drops_low_outliers() -> None:
    disp = np.full((20, 20), 0.8, dtype=np.float32)
    disp[10, 10] = 0.0  # a depth-model hole inside the object
    alpha = np.ones((20, 20), dtype=np.float32)
    core = trusted_core(alpha, disp, nb_pixels_remove=2, threshold=0.5, low_pct=2.0)
    assert not core[10, 10]  # the hole is excluded from the trusted core
    assert core.sum() > 0


def test_propagation_does_not_spread_low_outlier_when_cleaned() -> None:
    disp = np.full((20, 20), 0.8, dtype=np.float32)
    disp[10, 10] = 0.0
    alpha = np.ones((20, 20), dtype=np.float32)
    out = propagate_disparity(
        disp,
        alpha,
        nb_pixels_remove=2,
        threshold=0.5,
        low_pct=2.0,
    )
    # The hole value never propagates: the whole frame stays near 0.8.
    assert float(out.min()) > 0.5
