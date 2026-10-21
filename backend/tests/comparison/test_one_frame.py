"""Our renderer on one frame: the all-in-focus frame and its disparity as a single layer."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "comparison"))

from run_ours_one_frame import render_frame  # noqa: E402

SIZE = 64


def test_a_frame_in_focus_everywhere_is_returned_as_it_is() -> None:
    rgb = np.random.default_rng(0).random((SIZE, SIZE, 3), dtype=np.float32)
    disparity = np.full((SIZE, SIZE), 0.4, dtype=np.float32)
    out = render_frame(rgb, disparity, focus=0.4, strength=8.0)
    assert out == pytest.approx(rgb, abs=1e-4)


def test_a_defocused_point_of_light_spreads_into_a_disk() -> None:
    rgb = np.zeros((SIZE, SIZE, 3), dtype=np.float32)
    rgb[SIZE // 2, SIZE // 2] = 1.0
    disparity = np.full((SIZE, SIZE), 0.5, dtype=np.float32)
    # A radius of 0.25 * 32 = 8 pixels at the reference width of 1024, scaled to this width.
    out = render_frame(rgb, disparity, focus=0.25, strength=32.0 * 1024 / SIZE)
    lit = out[..., 0] > out[..., 0].max() * 0.5
    assert lit.sum() == pytest.approx(np.pi * 8**2, rel=0.2)
    assert not lit[0, 0]
