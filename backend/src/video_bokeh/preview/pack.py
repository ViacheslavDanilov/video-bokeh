#!/usr/bin/env python3
"""Pack per-frame streams into per-sequence MP4 files.

For each sequence under `<data-root>/sequences/<id>/`, reads each stream's frames
and writes `<stream>.mp4` alongside the frames. Streams named on the CLI
must be directories under each sequence (e.g. `all_in_focus`, later `bokeh`).

Alpha is a multi-page `.tif`, with one page per object (see `core/_streams.py`).
`render_object_masks` colors each object for the preview.

Disparity is a uint16 PNG (see `core/_streams.py`), not RGB, so it is
encoded through a colormap (`--colormap`, default `spectral_r`) rather
than through `Image.convert`.

Flow is a 16-bit KITTI PNG per frame but the last, colored as optical-flow
papers color it (`preview/_flow.py`), at one scale for the whole sequence.
A still frame stands for the last, so the video is as long as the others.
Backward flow (`flow_back`) is colored the same, with the still frame first,
and the occlusion mask is white on black, with a black frame last.

Layout:

    <data-root>/
    └── sequences/
        └── 0001/
            ├── all_in_focus/01.png … 80.png
            ├── all_in_focus.mp4               # written here
            ├── alpha/01.tif        … 80.tif
            └── alpha.mp4                       # written here

Usage:
    # Default: all sequences, all_in_focus stream, CRF 17
    uv run python -m video_bokeh.preview.pack \\
        --data-root backend/data/synth_dev

    # Multiple streams, custom fps
    uv run python -m video_bokeh.preview.pack \\
        --data-root backend/data/synth_dev \\
        --streams all_in_focus,alpha,bokeh \\
        --fps 30

    # Limit to specific sequences
    uv run python -m video_bokeh.preview.pack \\
        --data-root backend/data/synth_dev \\
        --seqs 0001,0003

    # Disparity, through the colormap
    uv run python -m video_bokeh.preview.pack \\
        --data-root backend/data/synth_dev \\
        --streams disparity --colormap spectral_r
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import imageio.v2 as iio
import numpy as np
from PIL import Image

from video_bokeh.core._seq_io import list_sequences, parse_names
from video_bokeh.core._streams import (
    read_alpha_tiff,
    read_disparity_png,
    read_flow_png,
    read_mask_png,
)
from video_bokeh.preview._colormap import COLORMAPS, apply_colormap
from video_bokeh.preview._flow import flow_to_rgb
from video_bokeh.preview._masks import render_object_masks

# --------------------------------------------------------------------------- #
# I/O                                                                         #
# --------------------------------------------------------------------------- #


#: What each stream is stored as. Alpha is multi-page TIFF because it carries one page
#: per object; everything else is PNG.
_STREAM_SUFFIX = {"alpha": "*.tif"}


def list_stream_frames(seq_dir: Path, stream: str) -> list[Path]:
    stream_dir = seq_dir / stream
    if not stream_dir.exists() or not stream_dir.is_dir():
        return []
    return sorted(stream_dir.glob(_STREAM_SUFFIX.get(stream, "*.png")))


# --------------------------------------------------------------------------- #
# Encoding                                                                    #
# --------------------------------------------------------------------------- #


def load_frame(path: Path, stream: str, colormap: str) -> np.ndarray:
    """Load one frame as uint8 RGB.

    The `alpha` stream is a multi-page TIFF and the `disparity` stream is a uint16
    PNG (see `core/_streams.py`), so each goes
    through `read_disparity_png` and the colormap rather than `Image.convert`,
    which would silently reinterpret it as garbage. Every other stream keeps
    the existing convert-to-RGB path.
    """
    if stream == "disparity":
        return apply_colormap(read_disparity_png(path), colormap)
    if stream == "alpha":
        # One page per object, colored by identity. See preview/_masks.py for why the
        # page index is the object and not its distance.
        return render_object_masks(read_alpha_tiff(path))
    img = Image.open(path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    return np.asarray(img, dtype=np.uint8)


def _flow_frames(paths: list[Path], backward: bool = False) -> Iterator[np.ndarray]:
    """A flow stream in color, and a still frame for the frame it has no field for.

    That is the last frame for the forward flow, which has no next frame, and the first
    for the backward flow, which has no previous one. Read twice rather than held: once
    for the fastest valid motion in the sequence, the scale every frame is colored at,
    once to color them. A vector the file marks invalid is drawn still.
    """
    top = 0.0
    shape = None
    for path in paths:
        flow, valid = read_flow_png(path)
        shape = flow.shape
        if valid.any():
            top = max(top, float(np.hypot(*flow[valid].T).max()))
    if shape is None:
        return
    still = flow_to_rgb(np.zeros(shape, dtype=np.float32), 1.0)
    if backward:
        yield still
    for path in paths:
        flow, valid = read_flow_png(path)
        flow[~valid] = 0
        yield flow_to_rgb(flow, top or 1.0)
    if not backward:
        yield still


#: The overlay grays the frames, at this much of their brightness: near full, so the
#: picture stays readable, and a little under it, so the orange stands out on white.
_OVERLAY_BRIGHTNESS = 0.9
#: How opaque the orange is over each occluded pixel.
_OVERLAY_OPACITY = 0.65
#: Orange from the Okabe-Ito palette, #E69F00, which reads apart from gray for every
#: common form of color blindness.
_ORANGE = np.array([230.0, 159.0, 0.0])
#: Rec. 709 luma weights, for the gray.
_LUMA = np.array([0.2126, 0.7152, 0.0722])


def _occlusion_frames(
    paths: list[Path],
    background: list[Path] | None,
) -> Iterator[np.ndarray]:
    """The occlusion stream, and a frame for the last, which has no next frame and so
    nothing known to be hidden.

    On its own each mask is white on black, as stored. Over ``background``, the
    all-in-focus frames, each frame is grayed and its occluded pixels drawn in a
    semi-transparent orange.
    """
    if background is None:
        mask = None
        for path in paths:
            mask = read_mask_png(path)
            yield np.repeat(np.where(mask, 255, 0).astype(np.uint8)[..., None], 3, -1)
        if mask is not None:
            yield np.zeros((*mask.shape, 3), dtype=np.uint8)
        return
    for index, frame in enumerate(background):
        luma = load_frame(frame, "all_in_focus", "") @ _LUMA
        gray = np.repeat((luma * _OVERLAY_BRIGHTNESS)[..., None], 3, -1)
        if index < len(paths):
            mask = read_mask_png(paths[index])[..., None]
            orange = gray * (1 - _OVERLAY_OPACITY) + _ORANGE * _OVERLAY_OPACITY
            gray = np.where(mask, orange, gray)
        yield gray.round().astype(np.uint8)


def encode_stream(
    frames: list[Path],
    out_path: Path,
    fps: int,
    quality: int,
    stream: str,
    colormap: str,
    background: list[Path] | None = None,
) -> None:
    """Encode frames as H.264 High, mapping quality 0..10 to CRF 51..17.

    ``background``, the all-in-focus frames, draws an ``occlusion`` stream over them.
    """
    if not 0 <= quality <= 10:
        raise ValueError("quality must be between 0 and 10")
    crf = round(51 - 3.4 * quality)
    # libx264 wants even spatial dimensions and yuv420p for broad compatibility.
    # The old default, imageio quality=10, meant lossless H.264 at CRF 0, which
    # uses High 4:4:4 Predictive even with yuv420p. Firefox's decoders refuse that
    # profile on Windows and macOS (dom/media/platforms/PDMFactory.cpp).
    # Explicit CRF and High now produce the High profile, confirmed by ffprobe.
    # Firefox playback was not tested here.
    # `cast` because imageio's writer is typed as an abstract base class but
    # the concrete subclass exposes `append_data`.
    writer = cast(
        Any,
        iio.get_writer(
            out_path,
            fps=fps,
            codec="libx264",
            quality=None,
            output_params=["-crf", str(crf), "-profile:v", "high"],
            pixelformat="yuv420p",
            macro_block_size=1,
        ),
    )
    if stream in ("flow", "flow_back"):
        images = _flow_frames(frames, backward=stream == "flow_back")
    elif stream == "occlusion":
        images = _occlusion_frames(frames, background)
    else:
        images = (load_frame(p, stream, colormap) for p in frames)
    with writer:
        for image in images:
            writer.append_data(image)


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="dataset root containing sequences/ (e.g. backend/data/synth_dev)",
    )
    parser.add_argument(
        "--streams",
        type=parse_names,
        default=["all_in_focus"],
        help="Comma-separated stream subdir names. Default: 'all_in_focus'.",
    )
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument(
        "--quality",
        type=int,
        choices=range(11),
        default=10,
        help="quality 0-10 (higher = better), mapped to CRF round(51 - 3.4 * quality). "
        "Default 10 is CRF 17. Lower if you need smaller files.",
    )
    parser.add_argument(
        "--seqs",
        type=parse_names,
        default=None,
        help="Comma-separated sequence ids (e.g. '0001,0003'). Default: all.",
    )
    parser.add_argument(
        "--colormap",
        choices=sorted(COLORMAPS),
        default="spectral_r",
        help="Colormap for the disparity stream. Default: 'spectral_r'.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    seqs = list_sequences(args.data_root, args.seqs)
    if not seqs:
        raise SystemExit(
            f"no sequences to process under {args.data_root / 'sequences'}",
        )

    for seq_dir in seqs:
        for stream in args.streams:
            frames = list_stream_frames(seq_dir, stream)
            out_path = seq_dir / f"{stream}.mp4"

            if not frames:
                print(f"  {seq_dir.name}/{stream}: no PNG frames, skip")
                continue

            print(f"  {seq_dir.name}/{stream}: encoding {len(frames)} frames")
            encode_stream(
                frames,
                out_path,
                args.fps,
                args.quality,
                stream,
                args.colormap,
            )

    print(f"\nDone. Videos in {args.data_root / 'sequences' / '<id>' / '<stream>.mp4'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
