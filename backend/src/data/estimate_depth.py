#!/usr/bin/env python3
"""Estimate per-frame depth maps with Depth Anything V2.

Reads `<root>/sequences/<id>/all_in_focus/*.png` and writes a sibling
`<root>/sequences/<id>/depth/*.tif` of float32 relative depth, one channel,
same H×W as the input frame.

Layout:

    <root>/
    └── sequences/
        └── 0001/
            ├── all_in_focus/01.png … 80.png   # input
            ├── alpha/01.png        … 80.png
            └── depth/01.tif        … 80.tif   # written here

Uses `transformers.AutoModelForDepthEstimation` with the official Depth
Anything V2 checkpoints on Hugging Face. Default is the smallest variant
(`Depth-Anything-V2-Small-hf`, ~25M params) so this runs on a laptop CPU/MPS.

Usage:
    uv run python -m data.estimate_depth \
        --root backend/data/synth_dev

    # Only specific sequences:
    uv run python -m data.estimate_depth \
        --root backend/data/synth_dev \
        --seqs 0001,0003

    # Heavier checkpoint on a GPU box:
    uv run python -m data.estimate_depth \
        --root  backend/data/synth_dev \
        --model depth-anything/Depth-Anything-V2-Large-hf \
        --device cuda
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import tifffile
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForDepthEstimation

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


def list_frames(seq_dir: Path) -> list[Path]:
    aif_dir = seq_dir / "all_in_focus"
    if not aif_dir.exists():
        raise FileNotFoundError(f"all_in_focus dir missing: {aif_dir}")
    return sorted(aif_dir.glob("*.png"))


# --------------------------------------------------------------------------- #
# Inference                                                                   #
# --------------------------------------------------------------------------- #


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


def estimate_depth(
    model: Any,
    processor: Any,
    device: torch.device,
    frames: list[Path],
    batch_size: int,
) -> list[np.ndarray]:
    out: list[np.ndarray] = []
    for i in range(0, len(frames), batch_size):
        batch_paths = frames[i : i + batch_size]
        images = [Image.open(p).convert("RGB") for p in batch_paths]
        sizes = [(img.height, img.width) for img in images]

        inputs = processor(images=images, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model(**inputs)

        # Resize each prediction back to its source resolution.
        depth = outputs.predicted_depth  # [B, H', W'] float
        for j, (h, w) in enumerate(sizes):
            d = torch.nn.functional.interpolate(
                depth[j : j + 1].unsqueeze(1),
                size=(h, w),
                mode="bicubic",
                align_corners=False,
            ).squeeze()
            out.append(d.detach().cpu().numpy().astype(np.float32))
    return out


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
        "--model",
        default="depth-anything/Depth-Anything-V2-Small-hf",
        help="HF model id; default is the smallest variant (~25M params).",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "mps", "cpu"),
        default="auto",
    )
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-estimate depth even if the .tif already exists.",
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

    device = select_device(args.device)
    print(f"Loading {args.model} on {device}")
    processor = AutoImageProcessor.from_pretrained(args.model)
    model = AutoModelForDepthEstimation.from_pretrained(args.model).to(device)
    model.eval()

    seqs = list_sequences(args.root, args.seqs)
    if not seqs:
        raise SystemExit(f"no sequences to process under {args.root / 'sequences'}")

    for seq_dir in seqs:
        frames = list_frames(seq_dir)
        depth_dir = seq_dir / "depth"
        depth_dir.mkdir(parents=True, exist_ok=True)

        todo: list[tuple[Path, Path]] = []
        for f in frames:
            out_path = depth_dir / f"{f.stem}.tif"
            if out_path.exists() and not args.overwrite:
                continue
            todo.append((f, out_path))

        if not todo:
            print(f"  {seq_dir.name}: up to date ({len(frames)} frames)")
            continue

        print(f"  {seq_dir.name}: {len(todo)}/{len(frames)} frames")
        in_paths = [t[0] for t in todo]
        out_paths = [t[1] for t in todo]
        depths = estimate_depth(model, processor, device, in_paths, args.batch_size)
        for out_path, d in zip(out_paths, depths, strict=True):
            tifffile.imwrite(out_path, d.astype(np.float32))

    print(f"\nDone. Depth in {args.root / 'sequences' / '<id>' / 'depth'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
