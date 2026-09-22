#!/usr/bin/env python3
"""Pack per-frame PNG streams into per-sequence MP4 files.

For each sequence under `<data-root>/sequences/<id>/`, reads `<stream>/*.png`
and writes `<stream>.mp4` alongside the frames. Streams named on the CLI
must be directories under each sequence (e.g. `all_in_focus`, `alpha`,
later `bokeh`). Single-channel grayscale frames (e.g. `alpha`) are
expanded to RGB at encode time so any video player handles them.

Disparity is a uint16 PNG (see `core/_streams.py`), not RGB, so it is
encoded through a colormap (`--colormap`, default `spectral_r`) rather
than through `Image.convert`.

Layout:

    <data-root>/
    └── sequences/
        └── 0001/
            ├── all_in_focus/01.png … 80.png
            ├── all_in_focus.mp4               # written here
            ├── alpha/01.png        … 80.png
            └── alpha.mp4                       # written here

Usage:
    # Default: all sequences, all_in_focus stream, visually lossless
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
from pathlib import Path
from typing import Any, cast

import imageio.v2 as iio
import numpy as np
from PIL import Image

from video_bokeh.core._streams import read_disparity_png
from video_bokeh.preview._colormap import COLORMAPS, apply_colormap

# --------------------------------------------------------------------------- #
# I/O                                                                         #
# --------------------------------------------------------------------------- #


def list_sequences(root: Path, seqs: list[str] | None) -> list[Path]:
    seq_root = root / "sequences"
    if not seq_root.exists():
        raise FileNotFoundError(f"sequences dir missing: {seq_root}")
    dirs = sorted(p for p in seq_root.iterdir() if p.is_dir())
    if seqs is None:
        return dirs
    wanted = set(seqs)
    picked = [p for p in dirs if p.name in wanted]
    missing = wanted - {p.name for p in picked}
    if missing:
        raise SystemExit(f"sequences not found under {seq_root}: {sorted(missing)}")
    return picked


def list_stream_frames(seq_dir: Path, stream: str) -> list[Path]:
    stream_dir = seq_dir / stream
    if not stream_dir.exists() or not stream_dir.is_dir():
        return []
    return sorted(stream_dir.glob("*.png"))


# --------------------------------------------------------------------------- #
# Encoding                                                                    #
# --------------------------------------------------------------------------- #


def load_frame(path: Path, stream: str, colormap: str) -> np.ndarray:
    """Load one frame as uint8 RGB.

    The `disparity` stream is a uint16 PNG (see `core/_streams.py`), so it goes
    through `read_disparity_png` and the colormap rather than `Image.convert`,
    which would silently reinterpret it as garbage. Every other stream keeps
    the existing convert-to-RGB path.
    """
    if stream == "disparity":
        return apply_colormap(read_disparity_png(path), colormap)
    img = Image.open(path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    return np.asarray(img, dtype=np.uint8)


def encode_stream(
    frames: list[Path],
    out_path: Path,
    fps: int,
    quality: int,
    stream: str,
    colormap: str,
) -> None:
    """Encode a sorted list of PNG frames to H.264 MP4."""
    # libx264 wants even spatial dimensions and yuv420p for broad compatibility.
    # `cast` because imageio's writer is typed as an abstract base class but
    # the concrete subclass exposes `append_data`.
    writer = cast(
        Any,
        iio.get_writer(
            out_path,
            fps=fps,
            codec="libx264",
            quality=quality,
            pixelformat="yuv420p",
            macro_block_size=1,
        ),
    )
    with writer:
        for p in frames:
            writer.append_data(load_frame(p, stream, colormap))


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
        type=lambda s: [c.strip() for c in s.split(",") if c.strip()],
        default=["all_in_focus"],
        help="Comma-separated stream subdir names. Default: 'all_in_focus'.",
    )
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument(
        "--quality",
        type=int,
        default=10,
        help="imageio/ffmpeg quality 0-10 (higher = better). Default 10 "
        "(visually lossless, ~CRF 17). Lower if you need smaller files.",
    )
    parser.add_argument(
        "--seqs",
        type=lambda s: [c.strip() for c in s.split(",") if c.strip()],
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
