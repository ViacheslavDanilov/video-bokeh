#!/usr/bin/env python3
"""Estimate per-frame disparity maps via a registered depth estimator.

This is the full-scene baseline: it runs the selected estimator on each
all-in-focus composite and writes float32 disparity TIFFs beside the frames.
For the high-accuracy dataset bake path, use data.fuse_per_object_disparity.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import tifffile
import torch
from PIL import Image

from data.depth import ESTIMATORS


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


def list_frames(seq_dir: Path) -> list[Path]:
    aif_dir = seq_dir / "all_in_focus"
    if not aif_dir.exists():
        raise FileNotFoundError(f"all_in_focus dir missing: {aif_dir}")
    return sorted(aif_dir.glob("*.png"))


def select_device(prefer: str) -> torch.device:
    if prefer == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    if prefer == "mps" and torch.backends.mps.is_available():
        return torch.device("mps")
    if prefer == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if torch.backends.mps.is_available():
            return torch.device("mps")
    return torch.device("cpu")


def _parse_seqs(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="dataset root containing sequences/ (e.g. backend/data/synth_dev)",
    )
    parser.add_argument(
        "--model",
        choices=sorted(ESTIMATORS.keys()),
        default="da2-small",
        help="Registered estimator key. See data.depth.ESTIMATORS.",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "mps", "cpu"),
        default="auto",
    )
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument(
        "--seqs",
        type=_parse_seqs,
        default=None,
        help="Comma-separated sequence ids (e.g. '0001,0003'). Default: all.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    device = select_device(args.device)
    print(f"Loading estimator {args.model!r} on {device}")
    estimator = ESTIMATORS[args.model]()
    estimator.load(device)

    seqs = list_sequences(args.data_root, args.seqs)
    if not seqs:
        raise SystemExit(
            f"no sequences to process under {args.data_root / 'sequences'}",
        )

    for seq_dir in seqs:
        frames = list_frames(seq_dir)
        if not frames:
            continue
        disparity_dir = seq_dir / "disparity"
        disparity_dir.mkdir(parents=True, exist_ok=True)
        print(f"  {seq_dir.name}: {len(frames)} frames")

        for i in range(0, len(frames), args.batch_size):
            batch_paths = frames[i : i + args.batch_size]
            images = [Image.open(path).convert("RGB") for path in batch_paths]
            disparities = estimator.infer(images)
            for path, disp in zip(batch_paths, disparities, strict=True):
                tifffile.imwrite(
                    disparity_dir / f"{path.stem}.tif",
                    disp.astype(np.float32),
                )

    print(f"\nDone. Disparity in {args.data_root / 'sequences' / '<id>' / 'disparity'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
