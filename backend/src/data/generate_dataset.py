#!/usr/bin/env python3
"""Stage B offline writer: materialize sampled scenes to the sequence layout.

    <output>/
    ├── manifest.csv
    └── sequences/<id>/{all_in_focus,alpha,disparity}/<frame>.png

This layout matches what prepare_any_to_bokeh.py consumes. Replaces the old
generate_sequences.py + estimate_disparity.py pair: depth is now sampled and
transformed from the library, not estimated per frame.

Usage:
    uv run python -m data.generate_dataset \\
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

from data._sequence_geometry import SampleConfig
from data.compositor import RenderedFrame, render_scene, sample_scene

_MANIFEST_FIELDS = (
    "seq_id",
    "seed",
    "n_frames",
    "size",
    "n_objects",
    "depth_mode",
    "n_rejections",
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
    channels = [
        np.clip(a * 255, 0, 255).astype(np.uint8) for a in frame.object_alphas[:3]
    ]
    h, w = frame.alpha.shape
    while len(channels) < 3:
        channels.append(np.zeros((h, w), dtype=np.uint8))
    Image.fromarray(np.stack(channels, axis=-1), "RGB").save(
        alp / f"{stem}.png",
        compress_level=6,
    )
    Image.fromarray(
        (np.clip(frame.disparity, 0, 1) * 255).round().astype(np.uint8),
        "L",
    ).save(disp / f"{stem}.png", compress_level=6)


def generate_dataset(
    library_root: Path,
    output: Path,
    count: int,
    n_frames: int,
    size: int,
    seed: int,
    n_objects_min: int = 1,
    n_objects_max: int = 3,
    cfg: SampleConfig | None = None,
    depth_mode: str = "fixed",
) -> None:
    cfg = cfg or SampleConfig()
    output.mkdir(parents=True, exist_ok=True)
    rows: list[list[str]] = []

    for i in range(count):
        seq_seed = seed + i
        n_obj = random.Random(f"nobj:{seq_seed}").randint(n_objects_min, n_objects_max)
        scene = sample_scene(
            library_root,
            seed=seq_seed,
            n_frames=n_frames,
            size=size,
            n_objects=n_obj,
            cfg=cfg,
            depth_mode=depth_mode,
        )
        frames = render_scene(scene)

        seq_name = f"{i + 1:04d}"
        seq_dir = output / "sequences" / seq_name
        aif = seq_dir / "all_in_focus"
        alp = seq_dir / "alpha"
        disp = seq_dir / "disparity"
        for d in (aif, alp, disp):
            d.mkdir(parents=True, exist_ok=True)
        digits = max(2, len(str(n_frames)))
        for fi, frame in enumerate(frames):
            _save_frame(frame, f"{fi + 1:0{digits}d}", aif, alp, disp)
        rows.append(
            [
                seq_name,
                str(seq_seed),
                str(n_frames),
                str(size),
                str(len(scene.objects)),
                depth_mode,
                str(scene.n_rejections),
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--frames", type=int, default=80)
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-objects-min", type=int, default=1)
    parser.add_argument("--n-objects-max", type=int, default=3)
    parser.add_argument(
        "--depth-mode",
        choices=("fixed", "dynamic"),
        default="fixed",
        help="fixed = disjoint slots (default); dynamic = z(t) tracks + validator.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    generate_dataset(
        library_root=args.library_root,
        output=args.output,
        count=args.count,
        n_frames=args.frames,
        size=args.size,
        seed=args.seed,
        n_objects_min=args.n_objects_min,
        n_objects_max=args.n_objects_max,
        depth_mode=args.depth_mode,
    )
    print(f"\nDone. Sequences in {args.output / 'sequences'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
