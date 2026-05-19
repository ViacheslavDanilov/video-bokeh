#!/usr/bin/env python3
"""Fuse per-object depth estimates into dataset disparity ground truth.

For each frame: replays the renderer's scene geometry, runs the chosen
estimator on each object composited onto a neutral textured BG and once on
the warped BG alone, percentile-clamps and scale-bands each result onto a
global [0, 1] disparity axis, and composites via the GT alpha layers in
paint order. Output is identical in path/shape/dtype/convention to
``estimate_disparity.py``:

    <data-root>/sequences/<id>/disparity/<frame>.tif   float32, larger = closer

Usage:
    # Default: DA-V2 large on all sequences
    uv run python -m data.fuse_per_object_disparity \\
        --data-root    backend/data/synth_dev \\
        --fg-data-root backend/data/magick_dev \\
        --bg-data-root backend/data/bg-20k_dev

    # Specific sequences, small variant for a quick sanity check
    uv run python -m data.fuse_per_object_disparity \\
        --data-root    backend/data/synth_dev \\
        --fg-data-root backend/data/magick_dev \\
        --bg-data-root backend/data/bg-20k_dev \\
        --model        da2-small \\
        --seqs         0001,0003
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import tifffile
from PIL import Image

from data._fusion import band_normalize, bg_normalize, composite_layers
from data._neutral_bg import make_textured_bg
from data._sequence_geometry import SampleConfig, replay_scene
from data.depth import ESTIMATORS
from data.estimate_disparity import list_sequences, select_device
from data.generate_sequences import LAYER_CHANNELS, SequenceSpec, read_manifest


def _parse_seqs(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _composite_on_neutral(fg_rgba: Image.Image, neutral_bg: Image.Image) -> Image.Image:
    """Alpha-composite an RGBA foreground onto the cached neutral texture."""
    fg = np.asarray(fg_rgba, dtype=np.float32)
    bg = np.asarray(neutral_bg, dtype=np.float32)
    alpha = fg[..., 3:4] / 255.0
    rgb = alpha * fg[..., :3] + (1.0 - alpha) * bg
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), mode="RGB")


def _load_alpha_layers(path: Path, n_channels: int) -> list[np.ndarray]:
    if n_channels > 3:
        raise ValueError(
            f"alpha_layers RGB PNG supports at most 3 channels, got {n_channels}",
        )
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
    return [rgb[..., channel] for channel in range(n_channels)]


def _process_sequence(
    spec: SequenceSpec,
    seq_dir: Path,
    fg_root: Path,
    bg_root: Path,
    cfg: SampleConfig,
    estimator: Any,
    neutral_bg_img: Image.Image,
    band_width: float,
    bg_band_top: float,
) -> None:
    depth_source = "manifest" if spec.object_depths else "replayed"
    replay = replay_scene(spec, fg_root, bg_root, cfg, validate_channel_refs=True)
    n_obj = len(replay.object_depths)
    if n_obj > LAYER_CHANNELS:
        raise ValueError(
            f"sequence {spec.seq_id}: {n_obj} objects > LAYER_CHANNELS="
            f"{LAYER_CHANNELS}; alpha_layers PNG can pack at most {LAYER_CHANNELS} layers.",
        )

    print(
        f"  {seq_dir.name}  n_obj={n_obj}  "
        f"frames={spec.n_frames}  depths={depth_source}",
    )

    layers_dir = seq_dir / "alpha_layers"
    if not layers_dir.exists():
        raise FileNotFoundError(f"alpha_layers dir missing: {layers_dir}")

    disparity_dir = seq_dir / "disparity"
    disparity_dir.mkdir(parents=True, exist_ok=True)
    digits = max(2, len(str(spec.n_frames)))

    for i, frame in enumerate(replay.frames):
        isolated = [
            _composite_on_neutral(rgba, neutral_bg_img) for rgba in frame.object_rgbas
        ]
        obj_disps = estimator.infer(isolated)
        [bg_disp] = estimator.infer([frame.bg_rgb])

        frame_name = f"{i + 1:0{digits}d}.png"
        alphas = _load_alpha_layers(layers_dir / frame_name, n_obj)
        obj_norms = [
            band_normalize(
                obj_disps[channel],
                alphas[channel],
                object_depth=replay.object_depths[channel],
                band_width=band_width,
                bg_band_top=bg_band_top,
            )
            for channel in range(n_obj)
        ]
        bg_norm = bg_normalize(bg_disp, bg_band_top=bg_band_top)
        final = composite_layers(bg_norm, obj_norms, alphas)

        tifffile.imwrite(
            disparity_dir / f"{i + 1:0{digits}d}.tif",
            final.astype(np.float32),
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--fg-data-root", type=Path, required=True)
    parser.add_argument("--bg-data-root", type=Path, required=True)
    parser.add_argument(
        "--model",
        choices=sorted(ESTIMATORS.keys()),
        default="da2-large",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "mps", "cpu"),
        default="auto",
    )
    parser.add_argument("--band-width", type=float, default=0.10)
    parser.add_argument("--bg-band-top", type=float, default=0.05)
    parser.add_argument("--neutral-bg-seed", type=int, default=0)
    parser.add_argument("--seqs", type=_parse_seqs, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    manifest_path = args.data_root / "manifest.csv"
    if not manifest_path.exists():
        raise SystemExit(f"manifest missing: {manifest_path}")

    specs = read_manifest(manifest_path)
    seq_dirs = {path.name: path for path in list_sequences(args.data_root, args.seqs)}
    wanted = set(seq_dirs)
    specs = [spec for spec in specs if f"{spec.seq_id:04d}" in wanted]
    if not specs:
        raise SystemExit("no matching sequences after applying --seqs filter")

    device = select_device(args.device)
    print(f"Loading estimator {args.model!r} on {device}")
    estimator = ESTIMATORS[args.model]()
    estimator.load(device)

    cfg = SampleConfig()
    neutral_cache: dict[int, Image.Image] = {}
    for spec in specs:
        seq_name = f"{spec.seq_id:04d}"
        if spec.size not in neutral_cache:
            neutral_cache[spec.size] = Image.fromarray(
                make_textured_bg(size=spec.size, seed=args.neutral_bg_seed),
                mode="RGB",
            )
        _process_sequence(
            spec,
            seq_dirs[seq_name],
            args.fg_data_root,
            args.bg_data_root,
            cfg,
            estimator,
            neutral_cache[spec.size],
            band_width=args.band_width,
            bg_band_top=args.bg_band_top,
        )

    print(f"\nDone. Disparity in {args.data_root / 'sequences' / '<id>' / 'disparity'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
