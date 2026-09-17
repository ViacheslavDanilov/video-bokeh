"""Round-trip tests for the on-disk stream formats.

Write and read live in one module precisely so they cannot drift, and these tests are what
holds that. Every assertion here is about the contract in docs/reference/dataset-layout.md.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from data._streams import (
    read_alpha_tiff,
    read_disparity_png,
    write_alpha_tiff,
    write_disparity_png,
)

_U8_STEP = 1.0 / 255.0
_U16_STEP = 1.0 / 65535.0


def _soft_mask(size: int, cx: int, cy: int, r: float) -> np.ndarray:
    """A disc with an anti-aliased rim, so the matte is genuinely soft."""
    y, x = np.ogrid[:size, :size]
    d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    return np.clip((r - d) / 3.0, 0.0, 1.0).astype(np.float32)


def test_alpha_round_trips_within_one_quantization_step(tmp_path: Path) -> None:
    masks = [_soft_mask(64, 20 + 8 * i, 30, 15.0) for i in range(5)]
    path = tmp_path / "01.tif"
    write_alpha_tiff(path, masks)
    back = read_alpha_tiff(path)

    assert len(back) == 5
    for original, restored in zip(masks, back, strict=True):
        assert restored.dtype == np.float32
        assert np.abs(restored - original).max() <= _U8_STEP


def test_alpha_preserves_page_order(tmp_path: Path) -> None:
    """Page k must come back as object k. Silent reordering would relabel objects."""
    masks = [np.full((8, 8), v, dtype=np.float32) for v in (0.1, 0.4, 0.6, 0.8, 1.0)]
    path = tmp_path / "01.tif"
    write_alpha_tiff(path, masks)

    means = [float(m.mean()) for m in read_alpha_tiff(path)]
    assert means == sorted(means)
    assert means[0] == pytest.approx(0.1, abs=_U8_STEP)
    assert means[-1] == pytest.approx(1.0, abs=_U8_STEP)


def test_alpha_keeps_soft_edges(tmp_path: Path) -> None:
    """Binarizing on the way through would destroy the matte the dataset exists for."""
    mask = _soft_mask(64, 32, 32, 20.0)
    path = tmp_path / "01.tif"
    write_alpha_tiff(path, [mask])

    restored = read_alpha_tiff(path)[0]
    partial = ((restored > 0.0) & (restored < 1.0)).sum()
    assert partial > 50, f"only {partial} partially transparent pixels survived"


def test_single_mask_is_still_a_valid_tiff(tmp_path: Path) -> None:
    path = tmp_path / "01.tif"
    write_alpha_tiff(path, [_soft_mask(16, 8, 8, 5.0)])

    assert len(read_alpha_tiff(path)) == 1
    with Image.open(path) as im:  # readable by Pillow, not only by tifffile
        assert im.mode == "L"


def test_alpha_rejects_an_empty_mask_list(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one mask"):
        write_alpha_tiff(tmp_path / "01.tif", [])


def test_alpha_rejects_mismatched_shapes(tmp_path: Path) -> None:
    masks = [np.zeros((8, 8), np.float32), np.zeros((8, 9), np.float32)]
    with pytest.raises(ValueError, match="same shape"):
        write_alpha_tiff(tmp_path / "01.tif", masks)


def test_disparity_round_trips_within_one_16_bit_step(tmp_path: Path) -> None:
    disp = np.linspace(0.0, 1.0, 64 * 64, dtype=np.float32).reshape(64, 64)
    path = tmp_path / "01.png"
    write_disparity_png(path, disp)
    back = read_disparity_png(path)

    assert back.dtype == np.float32
    assert np.abs(back - disp).max() <= _U16_STEP


def test_disparity_is_written_as_16_bit(tmp_path: Path) -> None:
    """8-bit would pass the round-trip test at a 256x coarser tolerance. Pin the depth."""
    path = tmp_path / "01.png"
    write_disparity_png(path, np.zeros((8, 8), np.float32))

    with Image.open(path) as im:
        assert im.mode == "I;16"
        assert np.asarray(im).dtype == np.uint16


def test_disparity_resolves_steps_8_bit_cannot(tmp_path: Path) -> None:
    """Two values a third of an 8-bit step apart must stay distinct."""
    disp = np.zeros((4, 4), np.float32)
    disp[0, 0] = 0.5
    disp[0, 1] = 0.5 + _U8_STEP / 3.0
    path = tmp_path / "01.png"
    write_disparity_png(path, disp)

    back = read_disparity_png(path)
    assert back[0, 0] != back[0, 1]


def test_disparity_clips_out_of_range_input(tmp_path: Path) -> None:
    disp = np.array([[-0.5, 0.5, 1.5]], dtype=np.float32)
    path = tmp_path / "01.png"
    write_disparity_png(path, disp)

    back = read_disparity_png(path)
    assert back[0, 0] == pytest.approx(0.0)
    assert back[0, 2] == pytest.approx(1.0)
