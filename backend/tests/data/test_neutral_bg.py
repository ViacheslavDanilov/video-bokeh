from __future__ import annotations

import numpy as np

from data._neutral_bg import make_textured_bg


def test_shape_and_dtype() -> None:
    img = make_textured_bg(size=64, seed=0)
    assert img.shape == (64, 64, 3)
    assert img.dtype == np.uint8


def test_deterministic_for_same_seed() -> None:
    first = make_textured_bg(size=128, seed=7)
    second = make_textured_bg(size=128, seed=7)
    assert np.array_equal(first, second)


def test_different_seeds_differ() -> None:
    first = make_textured_bg(size=128, seed=1)
    second = make_textured_bg(size=128, seed=2)
    assert not np.array_equal(first, second)


def test_values_clustered_around_midgray() -> None:
    img = make_textured_bg(size=256, seed=0)
    assert 100 < float(img.mean()) < 156
    assert img.min() > 60
    assert img.max() < 200
