from __future__ import annotations

import numpy as np
from PIL import Image

from data._neutral_bg import composite_on_neutral, make_textured_bg


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


def test_composite_on_neutral_opaque_object_overwrites_bg() -> None:
    neutral = Image.fromarray(make_textured_bg(size=16, seed=0), mode="RGB")
    fg = np.zeros((16, 16, 4), dtype=np.uint8)
    fg[..., 0] = 200  # red, fully opaque centre
    fg[6:10, 6:10, 3] = 255
    out = np.asarray(composite_on_neutral(Image.fromarray(fg, mode="RGBA"), neutral))
    assert out.shape == (16, 16, 3)
    assert int(out[7, 7, 0]) == 200  # opaque pixel kept the object colour


def test_composite_on_neutral_transparent_keeps_bg() -> None:
    neutral = Image.fromarray(make_textured_bg(size=16, seed=0), mode="RGB")
    fg = np.zeros((16, 16, 4), dtype=np.uint8)  # alpha all zero
    out = np.asarray(composite_on_neutral(Image.fromarray(fg, mode="RGBA"), neutral))
    assert np.array_equal(out, np.asarray(neutral))
