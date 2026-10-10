"""Round-trip tests for the on-disk stream formats.

Write and read live in one module precisely so they cannot drift, and these tests are what
holds that. Every assertion here is about the contract in docs/reference/dataset-layout.md.
"""

from __future__ import annotations

from pathlib import Path

import imagecodecs
import numpy as np
import pytest
from PIL import Image

from video_bokeh.core._streams import (
    read_alpha_tiff,
    read_disparity_png,
    read_disparity_tiff,
    read_flow_png,
    read_paint_order,
    read_rgb_tiff,
    write_alpha_tiff,
    write_bokeh,
    write_disparity_png,
    write_disparity_tiff,
    write_flow_png,
    write_paint_order,
    write_rgb_tiff,
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


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6, 7])
def test_every_object_count_writes_that_many_pages(tmp_path: Path, n: int) -> None:
    """Regression: tifffile infers meaning from shape unless told otherwise.

    A (3, H, W) array became one RGB page and (4, H, W) one RGBA page, so three and
    four masks -- the commonest counts -- were silently interleaved into a single
    colour image and read back as one mask. Only sweeping the count catches it: the
    boundary is invisible at 1, 2 and 5.
    """
    masks = [np.full((16, 16), (i + 1) / 10.0, dtype=np.float32) for i in range(n)]
    path = tmp_path / "01.tif"
    write_alpha_tiff(path, masks)

    back = read_alpha_tiff(path)
    assert len(back) == n
    for i, page in enumerate(back):
        assert page.shape == (16, 16)
        assert float(page.mean()) == pytest.approx((i + 1) / 10.0, abs=_U8_STEP)


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


def test_disparity_reader_rejects_an_8_bit_png(tmp_path: Path) -> None:
    """An 8-bit file read as 16-bit is wrong by 257x, silently, and exits 0.

    Datasets generated before the format change hold 8-bit disparity, nothing deletes
    them, and the bridge would turn one into a near-black stream and report success.
    """
    path = tmp_path / "01.png"
    Image.fromarray(np.full((4, 4), 204, dtype=np.uint8), mode="L").save(path)

    with pytest.raises(ValueError, match="16-bit"):
        read_disparity_png(path)


@pytest.mark.parametrize("n", [1, 3, 4, 5])
def test_object_colours_round_trip_one_page_each(tmp_path: Path, n: int) -> None:
    """Page k is object k's colour, at any count, read back exactly by Pillow.

    Three and four pages are the counts a shape-guessing writer folds into one image.
    """
    rng = np.random.default_rng(n)
    images = [rng.uniform(0, 255, (16, 16, 3)).astype(np.float32) for _ in range(n)]
    path = tmp_path / "01.tif"
    write_rgb_tiff(path, images)

    back = read_rgb_tiff(path)
    assert len(back) == n
    for original, restored in zip(images, back, strict=True):
        assert restored.dtype == np.float32
        assert restored.shape == (16, 16, 3)
        assert np.abs(restored - original).max() < 1.0  # truncated, not rounded
    with Image.open(path) as im:
        assert im.mode == "RGB"


@pytest.mark.parametrize("n", [1, 3, 4, 5])
def test_object_disparities_round_trip_in_16_bits(tmp_path: Path, n: int) -> None:
    maps = [np.full((8, 8), 0.5 + i * _U8_STEP / 3.0, np.float32) for i in range(n)]
    path = tmp_path / "01.tif"
    write_disparity_tiff(path, maps)

    back = read_disparity_tiff(path)
    assert len(back) == n
    for original, restored in zip(maps, back, strict=True):
        assert restored.dtype == np.float32
        assert np.abs(restored - original).max() <= _U16_STEP
    assert len({float(m[0, 0]) for m in back}) == n  # finer than 8 bits
    with Image.open(path) as im:
        assert np.asarray(im).dtype == np.uint16


def test_paint_order_round_trips(tmp_path: Path) -> None:
    orders = [[0, 2, 1], [2, 0, 1], [1, 0, 2]]
    path = tmp_path / "paint_order.json"
    write_paint_order(path, orders)
    assert read_paint_order(path) == orders


def test_a_paint_order_that_is_not_a_permutation_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "paint_order.json"
    write_paint_order(path, [[0, 1], [1, 1]])
    with pytest.raises(ValueError, match="frame 2"):
        read_paint_order(path)


def test_bokeh_written_beside_a_bokeh_already_there_leaves_it(tmp_path: Path) -> None:
    """Two requests adding bokeh to one sequence at once: the second keeps the first's."""
    (tmp_path / "all_in_focus").mkdir()
    (tmp_path / "bokeh").mkdir()
    (tmp_path / "bokeh" / "first.txt").write_text("first")
    write_bokeh(tmp_path, [("01.png", Image.new("RGB", (4, 4)))], {}, replace=False)
    assert (tmp_path / "bokeh" / "first.txt").is_file()
    assert not list(tmp_path.glob(".bokeh-*"))


def test_bokeh_written_again_replaces_the_old(tmp_path: Path) -> None:
    (tmp_path / "all_in_focus").mkdir()
    (tmp_path / "bokeh").mkdir()
    (tmp_path / "bokeh" / "old.txt").write_text("old")
    write_bokeh(tmp_path, [("01.png", Image.new("RGB", (4, 4)))], {"run": 2})
    assert not (tmp_path / "bokeh" / "old.txt").exists()
    assert (tmp_path / "bokeh" / "01.png").is_file()


def test_flow_round_trips_within_a_64th_of_a_pixel(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    flow = rng.uniform(-40.0, 40.0, size=(12, 16, 2)).astype(np.float32)
    write_flow_png(tmp_path / "f.png", flow)
    back, valid = read_flow_png(tmp_path / "f.png")
    assert back.shape == (12, 16, 2) and back.dtype == np.float32
    assert valid.all()
    assert np.abs(back - flow).max() <= 0.5 / 64 + 1e-6


def test_flow_is_kitti_16_bit_png(tmp_path: Path) -> None:
    """Red u * 64 + 2**15, green v * 64 + 2**15, blue 1 where valid."""
    flow = np.zeros((2, 3, 2), dtype=np.float32)
    flow[0, 0] = (1.0, -0.5)
    write_flow_png(tmp_path / "f.png", flow)
    raw = imagecodecs.png_decode((tmp_path / "f.png").read_bytes())
    assert raw.dtype == np.uint16 and raw.shape == (2, 3, 3)
    assert tuple(raw[0, 0]) == (2**15 + 64, 2**15 - 32, 1)
    assert tuple(raw[1, 2]) == (2**15, 2**15, 1)


def test_flow_out_of_range_reads_back_invalid(tmp_path: Path) -> None:
    flow = np.zeros((2, 2, 2), dtype=np.float32)
    flow[0, 1] = (600.0, 0.0)
    write_flow_png(tmp_path / "f.png", flow)
    _, valid = read_flow_png(tmp_path / "f.png")
    assert valid.tolist() == [[True, False], [True, True]]
