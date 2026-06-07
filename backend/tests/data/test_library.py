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
    depth = np.full((16, 16), 0.5, dtype=np.float32)
    write_foreground(tmp_path, "abc", rgb, alpha, depth)

    assert list_foregrounds(tmp_path) == ["abc"]
    asset = load_foreground(tmp_path, "abc")
    assert isinstance(asset, ForegroundAsset)
    assert asset.rgb.size == (16, 16)
    assert asset.depth.shape == (16, 16)
    assert np.allclose(asset.depth, 0.5, atol=1e-3)


def test_write_then_load_background_roundtrips(tmp_path) -> None:
    rgb = Image.new("RGB", (16, 16), (40, 50, 60))
    depth = np.full((16, 16), 0.2, dtype=np.float32)
    write_background(tmp_path, "bg1", rgb, depth)

    assert list_backgrounds(tmp_path) == ["bg1"]
    asset = load_background(tmp_path, "bg1")
    assert asset.rgb.size == (16, 16)
    assert np.allclose(asset.depth, 0.2, atol=1e-3)
