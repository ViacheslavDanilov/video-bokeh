"""The plane fit behind MPIB's ray tracer, on layers whose plane is known by construction."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "comparison"))

from planes import MIN_DISPARITY, fit_plane  # noqa: E402


def _grid(h: int = 16, w: int = 24) -> tuple[np.ndarray, np.ndarray]:
    ys, xs = np.mgrid[0:h, 0:w]
    return xs.astype(np.float64), ys.astype(np.float64)


def _disparity_of(a: float, b: float, c: float, shape: tuple[int, int]) -> np.ndarray:
    """The disparity ``(1 - a x - b y) / c`` that the ray tracer's own demo derives."""
    xs, ys = _grid(*shape)
    return (1.0 - a * xs - b * ys) / c


def test_a_flat_layer_is_a_plane_at_its_depth() -> None:
    disparity = np.full((16, 24), 0.4)
    a, b, c = fit_plane(disparity, np.ones((16, 24)))
    assert (a, b) == (pytest.approx(0.0, abs=1e-9), pytest.approx(0.0, abs=1e-9))
    assert c == pytest.approx(1.0 / 0.4)


def test_a_tilted_plane_is_recovered() -> None:
    a, b, c = -1e-3, 2e-3, 1.0 / 0.5
    disparity = _disparity_of(a, b, c, (16, 24))
    fitted = fit_plane(disparity, np.ones((16, 24)))
    assert fitted == pytest.approx((a, b, c), rel=1e-6)


def test_only_pixels_with_weight_are_fitted() -> None:
    disparity = _disparity_of(-1e-3, 0.0, 2.0, (16, 24))
    weight = np.zeros((16, 24))
    weight[:, :12] = 1.0
    disparity[:, 12:] = 99.0  # garbage where the layer has no alpha
    assert fit_plane(disparity, weight) == pytest.approx((-1e-3, 0.0, 2.0), rel=1e-6)


def test_too_few_pixels_give_a_flat_layer_at_their_own_disparity() -> None:
    disparity = np.zeros((8, 8))  # a layer stores zero where it has no alpha
    disparity[2, 3] = 0.5
    weight = np.zeros((8, 8))
    weight[2, 3] = 1.0
    assert fit_plane(disparity, weight) == (0.0, 0.0, pytest.approx(2.0))


def test_pixels_on_one_line_give_a_flat_layer() -> None:
    disparity = np.zeros((8, 8))
    disparity[3, 1:7] = 0.5
    weight = (disparity > 0).astype(np.float64)
    # A row of pixels fixes no tilt across the rows, so no tilt is invented.
    assert fit_plane(disparity, weight) == (0.0, 0.0, pytest.approx(2.0))


def test_fractional_weights_pull_the_fit_toward_the_heavier_pixels() -> None:
    disparity = np.zeros((8, 8))
    weight = np.zeros((8, 8))
    # Four pixels in general position on the plane d = 0.5 + 0.01 x, and one off it.
    for (y, x), w in {
        (1, 1): 1.0,
        (1, 6): 1.0,
        (6, 1): 1.0,
        (6, 6): 1.0,
        (3, 3): 1.0,
    }.items():
        disparity[y, x] = 0.5 + 0.01 * x
        weight[y, x] = w
    disparity[3, 3] = 0.9  # off the plane
    light = fit_plane(disparity, weight)
    weight[3, 3] = 0.01
    lighter = fit_plane(disparity, weight)
    exact = (-0.01 / 0.5, 0.0, 1.0 / 0.5)

    def distance(fit: tuple[float, float, float]) -> float:
        return float(np.linalg.norm(np.array(fit) - np.array(exact)))

    assert distance(lighter) < distance(light)
    assert lighter == pytest.approx(exact, abs=1e-2)
    weight[3, 3] = 1e-9
    assert fit_plane(disparity, weight) == pytest.approx(exact, abs=1e-6)


def test_a_plane_that_dips_below_the_minimum_is_flattened() -> None:
    ys, xs = _grid(16, 24)
    # A steep ramp from 0.3 at the left edge to below zero beyond the right edge.
    disparity = 0.3 - 0.02 * xs
    a, b, c = fit_plane(disparity, np.ones((16, 24)))
    assert (a, b) == (0.0, 0.0)
    assert c == pytest.approx(1.0 / float(np.mean(disparity)))
    assert c > 0 and 1.0 / c > MIN_DISPARITY
