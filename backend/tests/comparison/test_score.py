"""The comparison's scoring: PSNR and the band around object edges, on arrays whose answer
is known by construction."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "comparison"))

from score import edge_band, psnr  # noqa: E402


def test_identical_images_have_infinite_psnr() -> None:
    image = np.full((4, 4, 3), 100, dtype=np.uint8)
    assert psnr(image, image) == float("inf")


def test_psnr_of_a_known_error() -> None:
    a = np.zeros((2, 2, 3), dtype=np.uint8)
    b = np.full((2, 2, 3), 255, dtype=np.uint8)
    assert psnr(a, b) == pytest.approx(0.0)
    c = np.full((2, 2, 3), 16, dtype=np.uint8)
    # A mean squared error of 256 against a peak of 255.
    assert psnr(a, c) == pytest.approx(10 * np.log10(255.0**2 / 256.0))


def test_the_band_reaches_width_pixels_from_an_edge() -> None:
    alpha = np.zeros((32, 32), dtype=np.float32)
    alpha[:, 16:] = 1.0
    band = edge_band([alpha], width=4)
    # The step is between columns 15 and 16, marked on both, so the band holds 11 to 20.
    assert band[:, 11:21].all()
    assert not band[:, :11].any() and not band[:, 21:].any()


def test_no_edge_gives_an_empty_band() -> None:
    assert not edge_band([np.ones((8, 8), dtype=np.float32)], width=4).any()


def test_every_objects_edge_counts() -> None:
    first = np.zeros((32, 32), dtype=np.float32)
    first[:, 8:] = 1.0
    second = np.zeros((32, 32), dtype=np.float32)
    second[:, 24:] = 1.0
    band = edge_band([first, second], width=2)
    assert band[0, 8] and band[0, 24] and not band[0, 16]


def test_the_band_is_a_square_not_a_diamond() -> None:
    alpha = np.zeros((33, 33), dtype=np.float32)
    alpha[16, 16] = 1.0
    band = edge_band([alpha], width=4)
    # The edges are the pixel and its four neighbors. A square band of 4 reaches (12, 12)
    # from the neighbor at (15, 16), three rows and four columns away; a diamond would not.
    assert band[12, 12] and band[20, 20]
    assert band[11, 16] and not band[11, 11] and not band[21, 21]
