#!/usr/bin/env python3
"""Convert disparity .tif files to uint8 PNG visualizations.

For each requested stream (e.g. `disparity_image`, `disparity_video`),
reads `<root>/sequences/<id>/<stream>/*.tif` and writes a sibling
`<root>/sequences/<id>/<stream>_png/*.png` of the same H×W, single-channel
uint8 (mode 'L'). Normalization is per-sequence — global min/max across
every .tif in that stream — so frame-to-frame brightness stays consistent.
This matches the disparity input format any-to-bokeh expects (PNG converted
via `Image.open(...).convert('L')`, value range 0-255).

Layout:

    <root>/
    └── sequences/
        └── 0001/
            ├── disparity_image/01.tif      … 80.tif   # DA-V2 output
            ├── disparity_image_png/01.png  … 80.png   # written here
            ├── disparity_video/01.tif      … 80.tif   # VDA output
            └── disparity_video_png/01.png  … 80.png   # written here

Usage:
    # All sequences, both streams (default)
    uv run python -m data.convert_disparity \\
        --root backend/data/synth_dev

    # Just one stream
    uv run python -m data.convert_disparity \\
        --root backend/data/synth_dev \\
        --streams disparity_video

    # Specific sequences only
    uv run python -m data.convert_disparity \\
        --root backend/data/synth_dev \\
        --seqs 0001,0003

    # Re-render even if PNGs already exist
    uv run python -m data.convert_disparity \\
        --root backend/data/synth_dev \\
        --overwrite
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

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


# --------------------------------------------------------------------------- #
# Conversion                                                                  #
# --------------------------------------------------------------------------- #


def convert_sequence(disparity_dir: Path, png_dir: Path) -> int:
    """Render every .tif in `disparity_dir` to a uint8 PNG in `png_dir`,
    using global per-sequence min/max normalization. Returns the number of
    PNGs written. Caller is responsible for ensuring `png_dir` should be
    (re)written — this function always overwrites whatever's there."""
    tifs = sorted(disparity_dir.glob("*.tif"))
    if not tifs:
        return 0
    arrs = [tifffile.imread(p) for p in tifs]
    stack = np.asarray(arrs, dtype=np.float32)
    lo = float(stack.min())
    hi = float(stack.max())
    rng = max(hi - lo, 1e-6)
    png_dir.mkdir(parents=True, exist_ok=True)
    for tif_path, arr in zip(tifs, arrs, strict=True):
        norm = ((arr - lo) / rng * 255.0).clip(0, 255).astype(np.uint8)
        Image.fromarray(norm, mode="L").save(
            png_dir / f"{tif_path.stem}.png",
            compress_level=6,
        )
    return len(tifs)


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="dataset root containing sequences/ (e.g. backend/data/synth_dev)",
    )
    parser.add_argument(
        "--streams",
        type=lambda s: [c.strip() for c in s.split(",") if c.strip()],
        default=["disparity_image", "disparity_video"],
        help="Comma-separated source stream subdirs to convert. "
        "Default: 'disparity_image,disparity_video'.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-render PNGs even if <stream>_png/ already has the full set.",
    )
    parser.add_argument(
        "--seqs",
        type=lambda s: [c.strip() for c in s.split(",") if c.strip()],
        default=None,
        help="Comma-separated sequence ids (e.g. '0001,0003'). Default: all.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    seqs = list_sequences(args.root, args.seqs)
    if not seqs:
        raise SystemExit(f"no sequences to process under {args.root / 'sequences'}")

    for seq_dir in seqs:
        for stream in args.streams:
            disparity_dir = seq_dir / stream
            png_dir = seq_dir / f"{stream}_png"

            tifs = sorted(disparity_dir.glob("*.tif"))
            if not tifs:
                print(f"  {seq_dir.name}/{stream}: no .tif files, skip")
                continue

            existing = sorted(png_dir.glob("*.png")) if png_dir.exists() else []
            up_to_date = (
                not args.overwrite
                and len(existing) == len(tifs)
                and {p.stem for p in existing} == {p.stem for p in tifs}
            )
            if up_to_date:
                print(f"  {seq_dir.name}/{stream}: up to date ({len(tifs)} frames)")
                continue

            n = convert_sequence(disparity_dir, png_dir)
            print(f"  {seq_dir.name}/{stream}: wrote {n} PNG(s)")

    print(
        f"\nDone. PNGs in {args.root / 'sequences' / '<id>' / '<stream>_png'}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
