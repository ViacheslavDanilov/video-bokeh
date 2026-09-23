"""Packing disparity must go through the colormap, not through Image.convert."""

from __future__ import annotations

import numpy as np
from PIL import Image

from video_bokeh.core._streams import write_disparity_png
from video_bokeh.preview.pack import encode_stream, load_frame


def _write_ramp(path, height=8, width=16):
    ramp = np.tile(np.linspace(0.0, 1.0, width, dtype=np.float32), (height, 1))
    write_disparity_png(path, ramp)
    return ramp


def test_disparity_frame_loads_as_colour(tmp_path):
    p = tmp_path / "01.png"
    _write_ramp(p)
    rgb = load_frame(p, "disparity", "spectral_r")
    assert rgb.dtype == np.uint8 and rgb.shape[2] == 3
    assert rgb[0, -1, 0] > rgb[0, -1, 2], "the near end must read red"
    assert rgb[0, 0, 2] > rgb[0, 0, 0], "the far end must read blue"


def test_disparity_is_not_passed_through_convert(tmp_path):
    p = tmp_path / "01.png"
    _write_ramp(p)
    naive = np.asarray(Image.open(p).convert("RGB"), dtype=np.uint8)
    coloured = load_frame(p, "disparity", "spectral_r")
    assert not np.array_equal(naive, coloured)


def test_other_streams_are_unchanged(tmp_path):
    p = tmp_path / "01.png"
    Image.fromarray(np.full((8, 16, 3), 37, dtype=np.uint8)).save(p)
    assert (load_frame(p, "all_in_focus", "spectral_r") == 37).all()


def test_encodes_a_disparity_video(tmp_path):
    seq = tmp_path / "sequences" / "0001" / "disparity"
    seq.mkdir(parents=True)
    for i in range(1, 5):
        _write_ramp(seq / f"{i:02d}.png")
    out = seq.parent / "disparity.mp4"
    encode_stream(
        sorted(seq.glob("*.png")),
        out,
        fps=24,
        quality=10,
        stream="disparity",
        colormap="spectral_r",
    )
    assert out.exists() and out.stat().st_size > 0
