#!/usr/bin/env python3
"""Estimate per-frame disparity maps with Depth Anything V2.

Reads `<data-root>/sequences/<id>/all_in_focus/*.png` and writes a sibling
`<data-root>/sequences/<id>/disparity/*.tif` of float32 relative inverse depth
(disparity), one channel, same H×W as the input frame. Larger value = closer
to camera; smaller = farther. Values are unitless and only meaningful in
relative ordering — there is no metric scale.

Note: Depth Anything V2 publishes its head output as `predicted_depth`, but
the values are inverse depth (disparity) by convention inherited from MiDaS.
This script names the output accordingly.

Layout:

    <data-root>/
    └── sequences/
        └── 0001/
            ├── all_in_focus/01.png … 80.png   # input
            ├── alpha/01.png        … 80.png
            └── disparity/01.tif    … 80.tif   # written here

Uses `transformers.AutoModelForDepthEstimation` with the official Depth
Anything V2 checkpoints on Hugging Face. Three variants are wired up via
`--variant`:

    small  ~25M params  Apache-2.0    laptop CPU/MPS friendly  (default)
    base   ~98M params  CC-BY-NC-4.0  better edges, GPU recommended
    large  ~335M params CC-BY-NC-4.0  highest quality, GPU required

For anything outside this set (metric-depth checkpoints, community
fine-tunes), pass an explicit HF id with `--model` — it overrides `--variant`.

Usage:
    # Default: small variant on auto-selected device
    uv run python -m data.estimate_disparity \
        --data-root backend/data/synth_dev

    # Highest quality on a GPU box
    uv run python -m data.estimate_disparity \
        --data-root backend/data/synth_dev \
        --variant large \
        --device cuda

    # Explicit HF id (e.g. metric-depth fine-tune)
    uv run python -m data.estimate_disparity \
        --data-root backend/data/synth_dev \
        --model depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf

    # Only specific sequences:
    uv run python -m data.estimate_disparity \
        --data-root backend/data/synth_dev \
        --seqs 0001,0003
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

# Depth Anything V2 published checkpoints on Hugging Face. Pick a variant
# with `--variant` (small|base|large) for a one-word switch, or override the
# full HF id with `--model` (e.g. for a metric-depth or fine-tuned variant).
#
#   small  ~25M  Apache-2.0    laptop CPU/MPS friendly, default
#   base   ~98M  CC-BY-NC-4.0  better edges, GPU recommended
#   large  ~335M CC-BY-NC-4.0  highest quality, GPU required for reasonable speed
_DA2_VARIANTS: dict[str, str] = {
    "small": "depth-anything/Depth-Anything-V2-Small-hf",
    "base": "depth-anything/Depth-Anything-V2-Base-hf",
    "large": "depth-anything/Depth-Anything-V2-Large-hf",
}


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


def estimate_disparity(
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

        # HF field is named `predicted_depth` but values are disparity.
        disparity = outputs.predicted_depth  # [B, H', W'] float
        for j, (h, w) in enumerate(sizes):
            d = torch.nn.functional.interpolate(
                disparity[j : j + 1].unsqueeze(1),
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
        "--data-root",
        type=Path,
        required=True,
        help="dataset root containing sequences/ (e.g. backend/data/synth_dev)",
    )
    parser.add_argument(
        "--variant",
        choices=("small", "base", "large"),
        default="small",
        help="DA-V2 variant shortcut. small (~25M, Apache-2.0) is laptop-"
        "friendly default; base (~98M) and large (~335M) are CC-BY-NC and "
        "want a GPU. Ignored if --model is set.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override --variant with an explicit HF model id "
        "(e.g. a metric-depth or community fine-tune).",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "mps", "cpu"),
        default="auto",
    )
    parser.add_argument("--batch-size", type=int, default=1)
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
    model_id = args.model or _DA2_VARIANTS[args.variant]
    print(f"Loading {model_id} on {device}")
    processor = AutoImageProcessor.from_pretrained(model_id)
    model = AutoModelForDepthEstimation.from_pretrained(model_id).to(device)
    model.eval()

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
        disparities = estimate_disparity(
            model,
            processor,
            device,
            frames,
            args.batch_size,
        )
        for f, d in zip(frames, disparities, strict=True):
            tifffile.imwrite(disparity_dir / f"{f.stem}.tif", d.astype(np.float32))

    print(f"\nDone. Disparity in {args.data_root / 'sequences' / '<id>' / 'disparity'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
