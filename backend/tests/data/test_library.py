from __future__ import annotations

import numpy as np
from PIL import Image

from data._library import (
    ForegroundAsset,
    list_backgrounds,
    list_foregrounds,
    load_background,
    load_foreground,
    write_background,
    write_foreground,
)


def test_write_then_load_foreground_roundtrips(tmp_path) -> None:
    rgb = Image.new("RGBA", (16, 16), (10, 20, 30, 255))
    alpha = np.ones((16, 16), dtype=np.float32)
    # A gradient so relative structure is meaningful (depth PNG is normalized).
    depth = np.tile(np.linspace(2.0, 6.0, 16, dtype=np.float32), (16, 1))
    write_foreground(tmp_path, "abc", rgb, alpha, depth)

    assert list_foregrounds(tmp_path) == ["abc"]
    asset = load_foreground(tmp_path, "abc")
    assert isinstance(asset, ForegroundAsset)
    assert asset.rgb.size == (16, 16)
    assert asset.depth.shape == (16, 16)
    # Depth is min/max-normalized to [0, 1]; the gradient roundtrips faithfully.
    assert asset.depth.dtype == np.float32
    assert abs(float(asset.depth.min())) < 1e-3
    assert abs(float(asset.depth.max()) - 1.0) < 1e-3
    assert np.all(np.diff(asset.depth[0]) >= -1e-4)  # monotonic preserved


def test_depth_is_saved_as_png(tmp_path) -> None:
    rgb = Image.new("RGBA", (8, 8), (0, 0, 0, 255))
    depth = np.tile(np.linspace(0.0, 1.0, 8, dtype=np.float32), (8, 1))
    write_foreground(tmp_path, "abc", rgb, np.ones((8, 8), dtype=np.float32), depth)
    base = tmp_path / "foregrounds" / "abc"
    assert (base / "depth.png").exists()
    assert not (base / "depth.tif").exists()


def test_write_then_load_background_roundtrips(tmp_path) -> None:
    rgb = Image.new("RGB", (16, 16), (40, 50, 60))
    depth = np.tile(np.linspace(0.0, 1.0, 16, dtype=np.float32), (16, 1))
    write_background(tmp_path, "bg1", rgb, depth)

    assert list_backgrounds(tmp_path) == ["bg1"]
    asset = load_background(tmp_path, "bg1")
    assert asset.rgb.size == (16, 16)
    assert asset.depth.shape == (16, 16)
    assert abs(float(asset.depth.max()) - 1.0) < 1e-3


def test_constant_depth_roundtrips_without_error(tmp_path) -> None:
    rgb = Image.new("RGB", (8, 8), (0, 0, 0))
    write_background(tmp_path, "flat", rgb, np.full((8, 8), 0.5, dtype=np.float32))
    asset = load_background(tmp_path, "flat")
    assert asset.depth.shape == (8, 8)
    assert np.all(np.isfinite(asset.depth))
