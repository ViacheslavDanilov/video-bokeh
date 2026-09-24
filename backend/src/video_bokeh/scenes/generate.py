#!/usr/bin/env python3
"""Stage B offline writer: materialize sampled scenes to the sequence layout.

    <output>/
    ├── manifest.csv
    └── sequences/<id>/
        ├── all_in_focus/<frame>.png   RGB uint8
        ├── alpha/<frame>.tif          multi-page uint8, one page per object
        └── disparity/<frame>.png      uint16

This layout matches what bridge/any_to_bokeh.py consumes. Replaces the old
generate_sequences.py + estimate_disparity.py pair: depth is now sampled and
transformed from the library, not estimated per frame.

Usage:
    uv run python -m video_bokeh.scenes.generate \\
        --library-root data/library_dev \\
        --output       data/synth_dev \\
        --count 10 --frames 80 --size 1024 --seed 0
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

import numpy as np
from PIL import Image

from video_bokeh.core._sequence_geometry import SampleConfig
from video_bokeh.core._streams import write_alpha_tiff, write_disparity_png
from video_bokeh.scenes._compositor import (
    CollisionRetriesExhausted,
    RenderedFrame,
    render_scene,
    sample_scene,
)

_MANIFEST_FIELDS = (
    "seq_id",
    "seed",
    "n_frames",
    "size",
    "n_objects",
    "n_rejections",
    "n_range_fallbacks",
)


def _save_frame(
    frame: RenderedFrame,
    stem: str,
    aif: Path,
    alp: Path,
    disp: Path,
) -> None:
    Image.fromarray(np.clip(frame.rgb, 0, 255).astype(np.uint8), "RGB").save(
        aif / f"{stem}.png",
        compress_level=6,
    )
    write_alpha_tiff(alp / f"{stem}.tif", frame.object_alphas)
    write_disparity_png(disp / f"{stem}.png", frame.disparity)


def write_sequence(seq_dir: Path, frames: list[RenderedFrame]) -> None:
    """Write one sequence's three streams into ``seq_dir``.

    The frame-number width comes from the frame count, so an 80-frame sequence is
    ``01``..``80`` and a 100-frame one is ``001``..``100``. The bridge and
    ``preview.pack`` both sort on the numeric prefix, so the width only has to be
    consistent inside a sequence.
    """
    aif = seq_dir / "all_in_focus"
    alp = seq_dir / "alpha"
    disp = seq_dir / "disparity"
    for d in (aif, alp, disp):
        d.mkdir(parents=True, exist_ok=True)
    digits = max(2, len(str(len(frames))))
    for fi, frame in enumerate(frames):
        _save_frame(frame, f"{fi + 1:0{digits}d}", aif, alp, disp)


def generate_dataset(
    library_root: Path,
    output: Path,
    count: int,
    n_frames: int,
    size: int,
    seed: int,
    n_objects_min: int = 1,
    n_objects_max: int = 5,
    cfg: SampleConfig | None = None,
) -> int:
    """Write ``count`` sequences and return how many were actually written.

    A sequence whose trajectories cannot be made collision-free is skipped, not
    written. Sequence names stay tied to the seed, so a skip leaves a gap in the
    numbering rather than shifting every later sequence onto a different seed.
    """
    cfg = cfg or SampleConfig()
    output.mkdir(parents=True, exist_ok=True)
    rows: list[list[str]] = []
    skipped: list[int] = []

    for i in range(count):
        seq_seed = seed + i
        n_obj = random.Random(f"nobj:{seq_seed}").randint(n_objects_min, n_objects_max)
        try:
            scene = sample_scene(
                library_root,
                seed=seq_seed,
                n_frames=n_frames,
                size=size,
                n_objects=n_obj,
                cfg=cfg,
            )
        except CollisionRetriesExhausted as exc:
            skipped.append(seq_seed)
            print(f"  skip  seed={seq_seed}  {exc}")
            continue
        frames = render_scene(scene)

        seq_name = f"{i + 1:04d}"
        write_sequence(output / "sequences" / seq_name, frames)
        rows.append(
            [
                seq_name,
                str(seq_seed),
                str(n_frames),
                str(size),
                str(len(scene.objects)),
                str(scene.n_rejections),
                str(scene.n_range_fallbacks),
            ],
        )
        print(
            f"  {seq_name}  seed={seq_seed}  "
            f"n_obj={len(scene.objects)}  frames={n_frames}",
        )

    with (output / "manifest.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_MANIFEST_FIELDS)
        writer.writerows(rows)

    if skipped:
        print(f"\nSkipped {len(skipped)} of {count} sequences; seeds: {skipped}")
    return len(rows)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--frames", type=int, default=80)
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-objects-min", type=int, default=1)
    parser.add_argument("--n-objects-max", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        written = generate_dataset(
            library_root=args.library_root,
            output=args.output,
            count=args.count,
            n_frames=args.frames,
            size=args.size,
            seed=args.seed,
            n_objects_min=args.n_objects_min,
            n_objects_max=args.n_objects_max,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(f"\nDone. {written} sequences in {args.output / 'sequences'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
