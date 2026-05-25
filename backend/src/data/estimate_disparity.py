#!/usr/bin/env python3
"""Estimate disparity ground truth for synthetic sequences.

Per-object depth fusion: replays each sequence's scene geometry, runs the
chosen estimator on every object composited onto a neutral textured BG and
once on the warped BG alone, percentile-clamps and scale-bands each result
onto a global [0, 1] disparity axis, and composites via the GT alpha layers
in paint order. The output is the disparity GT consumed by any-to-bokeh.

Output (default --format png):

    <data-root>/sequences/<id>/disparity/<frame>.png   uint8 (mode 'L'), larger = closer

With --format tif, writes float32 .tif instead (preserves full precision).
The PNG default matches what any-to-bokeh consumes (uint8 in [0, 255]) and
renders correctly in standard image viewers; use TIF when you need the
unquantized [0, 1] disparity for ablations or re-fusion.

Usage:
    # Default: DA-V2 large on all sequences, uint8 PNG output
    uv run python -m data.estimate_disparity \\
        --data-root    backend/data/synth_dev \\
        --fg-data-root backend/data/magick_dev \\
        --bg-data-root backend/data/bg-20k_dev

    # Specific sequences, small variant for a quick sanity check
    uv run python -m data.estimate_disparity \\
        --data-root    backend/data/synth_dev \\
        --fg-data-root backend/data/magick_dev \\
        --bg-data-root backend/data/bg-20k_dev \\
        --model        da2-small \\
        --seqs         0001,0003

    # Keep float32 .tif (e.g. for ablations needing full precision)
    uv run python -m data.estimate_disparity \\
        --data-root    backend/data/synth_dev \\
        --fg-data-root backend/data/magick_dev \\
        --bg-data-root backend/data/bg-20k_dev \\
        --format       tif
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
from data._seq_io import list_sequences, select_device
from data._sequence_geometry import SampleConfig, replay_scene
from data.depth import ESTIMATORS
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


DISPARITY_FORMATS = ("png", "tif")


def _write_disparity(path: Path, arr: np.ndarray, fmt: str) -> None:
    """Persist a [0, 1] disparity map. PNG → uint8 mode 'L'; TIF → float32."""
    if fmt == "tif":
        tifffile.imwrite(path.with_suffix(".tif"), arr.astype(np.float32))
        return
    quantized = (np.clip(arr, 0.0, 1.0) * 255.0).round().astype(np.uint8)
    Image.fromarray(quantized, mode="L").save(
        path.with_suffix(".png"),
        compress_level=6,
    )


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
    disparity_format: str,
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

        _write_disparity(
            disparity_dir / f"{i + 1:0{digits}d}",
            final,
            disparity_format,
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
    parser.add_argument(
        "--format",
        dest="disparity_format",
        choices=DISPARITY_FORMATS,
        default="png",
        help="Disparity encoding: 'png' (uint16, default) or 'tif' (float32).",
    )
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
            disparity_format=args.disparity_format,
        )

    print(f"\nDone. Disparity in {args.data_root / 'sequences' / '<id>' / 'disparity'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
