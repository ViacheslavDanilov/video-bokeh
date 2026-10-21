"""Our renderer on one frame: the all-in-focus frame and its disparity as a single layer."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "comparison"))

from run_ours_one_frame import render_frame  # noqa: E402

from video_bokeh.layered import LayeredFrame, render_sequence  # noqa: E402

SIZE = 64


def _frame(rgb: np.ndarray, disparity: np.ndarray) -> LayeredFrame:
    """A frame with a background and no objects, as the renderer takes it."""
    return LayeredFrame(
        background=rgb.transpose(2, 0, 1),
        background_disparity=disparity[None],
        object_rgbs=np.zeros((0, 3, SIZE, SIZE), dtype=np.float32),
        object_alphas=np.zeros((0, SIZE, SIZE), dtype=np.float32),
        object_disparities=np.zeros((0, SIZE, SIZE), dtype=np.float32),
        paint_order=[],
    )


def test_a_frame_in_focus_everywhere_is_returned_as_it_is() -> None:
    rgb = np.random.default_rng(0).random((SIZE, SIZE, 3), dtype=np.float32)
    disparity = np.full((SIZE, SIZE), 0.4, dtype=np.float32)
    out = render_frame(rgb, disparity, focus=0.4, strength=8.0)
    assert out == pytest.approx(rgb, abs=1e-4)


def test_it_renders_what_the_sequence_renderer_renders_from_the_same_layer() -> None:
    rng = np.random.default_rng(1)
    rgb = rng.random((SIZE, SIZE, 3), dtype=np.float32)
    disparity = rng.random((SIZE, SIZE), dtype=np.float32)
    focus, strength = 0.3, 24.0 * 1024 / SIZE
    (expected,) = render_sequence(
        [_frame(rgb, disparity)], [focus], strength, device=torch.device("cpu")
    )
    out = render_frame(rgb, disparity, focus=focus, strength=strength)
    got = np.round(np.clip(out, 0.0, 1.0) * 255.0).astype(np.uint8)
    assert np.array_equal(got, np.asarray(expected))
