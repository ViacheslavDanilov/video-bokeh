#!/usr/bin/env python3
"""Estimate per-frame disparity for sequences with Video Depth Anything (VDA).

Companion to `estimate_disparity.py`. That script uses Depth Anything V2,
which is fast on laptop CPU/MPS but per-frame and therefore flickers across
time. This script uses VDA (github.com/DepthAnything/Video-Depth-Anything),
which processes the full 80-frame stack with built-in sliding-window
stitching for temporal consistency. CUDA-only in practice — VDA pins
xformers and torch versions that don't run on Apple Silicon. Use this on a
server before generating bokeh GT.

Output is identical in shape, dtype, and convention to `estimate_disparity.py`
(float32, same H×W as input, MiDaS-style: larger = closer, smaller = farther),
so downstream code does not need to know which estimator produced it. Both
scripts write to `<seq>/disparity/*.tif` — re-running this overwrites the
DA-V2 output for the same sequence (use `--seqs` to limit scope).

Layout:

    <root>/
    └── sequences/
        └── 0001/
            ├── all_in_focus/01.png … 80.png   # input
            ├── alpha/01.png        … 80.png
            └── disparity/01.tif    … 80.tif   # written here

Setup (on the CUDA box, once):

    backend/scripts/setup_third_party.sh

That script initializes the VDA + any-to-bokeh submodules under
backend/third_party/, creates a shared venv at backend/third_party/.venv,
installs both tools' requirements, and downloads the VDA-Small checkpoint
into backend/models/video_depth_anything/.

Usage:

    source backend/third_party/.venv/bin/activate
    PYTHONPATH=backend/third_party/Video-Depth-Anything \\
        python -m data.estimate_video_disparity \\
        --root backend/data/synth_dev

VDA is not added to pyproject.toml — its pinned numpy<2 / torch 2.1.1 /
xformers==0.0.23 deps would break the project's main lockfile. The shared
third-party venv keeps it isolated from the main project.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import tifffile
import torch
from PIL import Image

# Mirrors `model_configs` in the upstream VDA `run.py`. ViT-B is published
# but not exposed here to keep the surface narrow; add if needed.
_MODEL_CONFIGS: dict[str, dict[str, Any]] = {
    "vits": {"encoder": "vits", "features": 64, "out_channels": [48, 96, 192, 384]},
    "vitl": {
        "encoder": "vitl",
        "features": 256,
        "out_channels": [256, 512, 1024, 1024],
    },
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


def load_frames(paths: list[Path]) -> np.ndarray:
    arrs = [np.asarray(Image.open(p).convert("RGB"), dtype=np.uint8) for p in paths]
    return np.stack(arrs, axis=0)


# --------------------------------------------------------------------------- #
# Inference                                                                   #
# --------------------------------------------------------------------------- #


def load_model(checkpoint: Path, encoder: str, device: torch.device) -> Any:
    # Lazy import: VDA is server-only and not on PYTHONPATH at dev time.
    import video_depth_anything.video_depth as _vda  # ty: ignore[unresolved-import]

    cfg = _MODEL_CONFIGS[encoder]
    model = _vda.VideoDepthAnything(**cfg)
    state = torch.load(checkpoint, map_location="cpu")
    model.load_state_dict(state, strict=True)
    return model.to(device).eval()


def estimate_disparity(
    model: Any,
    frames: np.ndarray,
    fps: float,
    input_size: int,
    fp32: bool,
    device: torch.device,
) -> np.ndarray:
    depths, _ = model.infer_video_depth(
        frames,
        target_fps=fps,
        input_size=input_size,
        device=str(device),
        fp32=fp32,
    )
    return np.asarray(depths, dtype=np.float32)


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
        "--checkpoint",
        type=Path,
        default=Path(
            "backend/models/video_depth_anything/video_depth_anything_vits.pth",
        ),
        help="Path to video_depth_anything_<vits|vitl>.pth "
        "(default: backend/models/video_depth_anything/video_depth_anything_vits.pth)",
    )
    parser.add_argument(
        "--encoder",
        choices=("vits", "vitl"),
        default="vits",
        help="Model size; default 'vits' (Apache-2.0). 'vitl' is CC-BY-NC.",
    )
    parser.add_argument(
        "--input-size",
        type=int,
        default=518,
        help="Network internal resolution (VDA default).",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=24.0,
        help="Nominal fps for the input frame stack; VDA does not resample at this fps.",
    )
    parser.add_argument(
        "--fp32",
        action="store_true",
        help="Run in fp32 (default fp16).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-estimate disparity even if all .tif files already exist.",
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

    # VDA needs CUDA in practice (xformers pin, no MPS path).
    if not torch.cuda.is_available():
        raise SystemExit(
            "CUDA is required for VDA. Use estimate_disparity.py for CPU/MPS dev.",
        )
    device = torch.device("cuda")

    print(f"Loading VDA-{args.encoder} on {device}")
    model = load_model(args.checkpoint, args.encoder, device)

    seqs = list_sequences(args.root, args.seqs)
    if not seqs:
        raise SystemExit(f"no sequences to process under {args.root / 'sequences'}")

    for seq_dir in seqs:
        frames = list_frames(seq_dir)
        disparity_dir = seq_dir / "disparity"
        disparity_dir.mkdir(parents=True, exist_ok=True)

        out_paths = [disparity_dir / f"{f.stem}.tif" for f in frames]
        # VDA must see the full stack for temporal stitching, so skipping is
        # all-or-nothing per sequence.
        if not args.overwrite and all(p.exists() for p in out_paths):
            print(f"  {seq_dir.name}: up to date ({len(frames)} frames)")
            continue

        print(f"  {seq_dir.name}: {len(frames)} frames")
        stack = load_frames(frames)
        disparity = estimate_disparity(
            model,
            stack,
            fps=args.fps,
            input_size=args.input_size,
            fp32=args.fp32,
            device=device,
        )
        if disparity.shape[0] != len(frames):
            raise RuntimeError(
                f"VDA returned {disparity.shape[0]} frames; expected {len(frames)}",
            )
        for out_path, d in zip(out_paths, disparity, strict=True):
            tifffile.imwrite(out_path, d.astype(np.float32))

    print(f"\nDone. Disparity in {args.root / 'sequences' / '<id>' / 'disparity'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
