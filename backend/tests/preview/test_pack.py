"""Packing disparity must go through the colormap, not through Image.convert."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import imageio.v2 as iio
import imageio_ffmpeg
import numpy as np
import pytest
from PIL import Image

from video_bokeh.core._streams import write_disparity_png
from video_bokeh.preview.pack import _build_parser, encode_stream, load_frame


def _write_ramp(path, height=8, width=16):
    ramp = np.tile(np.linspace(0.0, 1.0, width, dtype=np.float32), (height, 1))
    write_disparity_png(path, ramp)
    return ramp


def test_disparity_frame_loads_as_color(tmp_path):
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
    colored = load_frame(p, "disparity", "spectral_r")
    assert not np.array_equal(naive, colored)


def test_other_streams_are_unchanged(tmp_path):
    p = tmp_path / "01.png"
    Image.fromarray(np.full((8, 16, 3), 37, dtype=np.uint8)).save(p)
    assert (load_frame(p, "all_in_focus", "spectral_r") == 37).all()


@pytest.mark.parametrize("quality,crf", [(0, "51"), (5, "34"), (10, "17")])
def test_quality_maps_to_explicit_crf_and_high_profile(
    tmp_path, monkeypatch, quality, crf
):
    writer_factory = MagicMock()
    monkeypatch.setattr("video_bokeh.preview.pack.iio.get_writer", writer_factory)
    frame = tmp_path / "01.png"
    _write_ramp(frame)

    encode_stream(
        [frame], tmp_path / "disparity.mp4", 24, quality, "disparity", "spectral_r"
    )

    kwargs = writer_factory.call_args.kwargs
    assert kwargs["output_params"] == ["-crf", crf, "-profile:v", "high"]
    assert kwargs["quality"] is None
    assert writer_factory.return_value.append_data.call_count == 1


@pytest.mark.parametrize("quality", [0, 5, 10])
def test_encodes_a_disparity_video(tmp_path, quality):
    seq = tmp_path / "sequences" / "0001" / "disparity"
    seq.mkdir(parents=True)
    for i in range(1, 5):
        _write_ramp(seq / f"{i:02d}.png")
    out = seq.parent / "disparity.mp4"
    encode_stream(
        sorted(seq.glob("*.png")),
        out,
        fps=24,
        quality=quality,
        stream="disparity",
        colormap="spectral_r",
    )
    assert out.exists() and out.stat().st_size > 0
    probe = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(out), "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Video: h264 (High)" in probe.stderr
    assert "yuv420p" in probe.stderr


def test_lower_quality_reduces_size_and_fidelity(tmp_path):
    rng = np.random.default_rng(0)
    source = np.repeat(rng.integers(0, 256, (64, 64, 1), dtype=np.uint8), 3, axis=2)
    frame = tmp_path / "01.png"
    Image.fromarray(source).save(frame)
    errors = {}
    sizes = {}
    for quality in (0, 10):
        out = tmp_path / f"quality-{quality}.mp4"
        encode_stream([frame], out, 24, quality, "all_in_focus", "spectral_r")
        with iio.get_reader(out) as reader:
            decoded = np.asarray(reader.get_data(0), dtype=np.float64)
        errors[quality] = np.square(decoded - source).mean()
        sizes[quality] = out.stat().st_size
    assert errors[10] < errors[0]
    assert sizes[10] > sizes[0]


@pytest.mark.parametrize("quality", [-1, 11])
def test_rejects_quality_outside_the_cli_scale(tmp_path, quality):
    with pytest.raises(SystemExit):
        _build_parser().parse_args(
            ["--data-root", str(tmp_path), "--quality", str(quality)]
        )
    with pytest.raises(ValueError, match="quality must be between 0 and 10"):
        encode_stream(
            [], tmp_path / "bad.mp4", 24, quality, "all_in_focus", "spectral_r"
        )
