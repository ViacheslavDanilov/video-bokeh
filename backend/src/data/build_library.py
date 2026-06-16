#!/usr/bin/env python3
"""Build the precomputed artifact library (Stage A).

For every foreground: composite the cut-out onto a neutral textured background,
run the depth estimator once, propagate the in-object disparity to a full-frame
map (Valery's edge refinement), and store rgb/alpha/depth. For every background:
run the estimator on the whole image and store rgb/depth.

Usage:
    uv run python -m data.build_library \\
        --fg-data-root data/magick_dev \\
        --bg-data-root data/bg-20k_dev \\
        --output       data/library_dev \\
        --size 1024 --model da2-large
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from data._library import FOREGROUNDS, write_background, write_foreground
from data._metadata import write_asset_metadata
from data._neutral_bg import composite_on_neutral, make_textured_bg
from data._propagation import propagate_disparity, trusted_core
from data._seq_io import select_device
from data._sequence_geometry import prepare_background, prepare_foreground
from data.depth import ESTIMATORS

DEFAULT_KEEP_SUBJECTS = ("person", "animal", "plant", "food", "object")
DEFAULT_KEEP_STYLES = ("photo", "render")
# Backgrounds are stored oversized so Stage B's pan/zoom/tilt warp never samples
# past the source edge (which would leave black holes in the frame). A sweep over
# 40 bg-pose seeds needs >= 0.20 to stay hole-free with the default motion ranges;
# 0.25 leaves headroom. Raise it if you widen bg_pan / bg_zoom in SampleConfig.
DEFAULT_BG_MARGIN = 0.25


def _ref_to_id(ref: str) -> str:
    """Filesystem-safe asset id from a relative image ref ('0L/abc.png' -> '0L__abc')."""
    return Path(ref).with_suffix("").as_posix().replace("/", "__")


def _list_foreground_refs(
    fg_root: Path,
    subjects: tuple[str, ...],
    styles: tuple[str, ...],
    subject_thr: float,
) -> list[str]:
    root = fg_root / "images"
    if not root.exists():
        raise FileNotFoundError(f"foreground images dir missing: {root}")
    refs = sorted(str(p.relative_to(root)) for p in root.rglob("*.png") if p.is_file())
    preds_path = fg_root / "predictions.csv"
    if not preds_path.exists() or not (subjects or styles or subject_thr > 0.0):
        return refs
    preds = pd.read_csv(preds_path, encoding="utf-8-sig").set_index("page_id")
    mask = pd.Series(True, index=preds.index)
    if subjects:
        mask &= preds["top_subject"].isin(list(subjects))
    if styles:
        mask &= preds["top_style"].isin(list(styles))
    if subject_thr > 0.0:
        mask &= preds["top_subject_score"] >= subject_thr
    kept = set(preds.index[mask])
    return [r for r in refs if Path(r).stem in kept]


def _list_background_refs(bg_root: Path) -> list[str]:
    root = bg_root / "images"
    if not root.exists():
        raise FileNotFoundError(f"background images dir missing: {root}")
    refs: list[str] = []
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        refs.extend(str(p.relative_to(root)) for p in root.rglob(ext) if p.is_file())
    return sorted(refs)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fg-data-root", type=Path, required=True)
    parser.add_argument("--bg-data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--model", choices=sorted(ESTIMATORS), default="da2-large")
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "mps", "cpu"),
        default="auto",
    )
    parser.add_argument("--neutral-bg-seed", type=int, default=0)
    parser.add_argument(
        "--bg-margin",
        type=float,
        default=DEFAULT_BG_MARGIN,
        help="oversize backgrounds by this fraction per side so Stage B's warp "
        f"leaves no black borders (default: {DEFAULT_BG_MARGIN}).",
    )
    parser.add_argument("--nb-pixels-remove", type=int, default=5)
    parser.add_argument("--alpha-threshold", type=float, default=0.04)
    parser.add_argument(
        "--low-pct",
        type=float,
        default=2.0,
        help="drop trusted-core pixels below this percentile as depth holes "
        "(0 disables cleanup).",
    )
    parser.add_argument("--limit-fg", type=int, default=None, help="cap foregrounds")
    parser.add_argument("--limit-bg", type=int, default=None, help="cap backgrounds")
    parser.add_argument(
        "--subjects",
        type=lambda s: tuple(c.strip() for c in s.split(",") if c.strip()),
        default=DEFAULT_KEEP_SUBJECTS,
    )
    parser.add_argument(
        "--styles",
        type=lambda s: tuple(c.strip() for c in s.split(",") if c.strip()),
        default=DEFAULT_KEEP_STYLES,
    )
    parser.add_argument("--subject-thr", type=float, default=0.50)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    fg_refs = _list_foreground_refs(
        args.fg_data_root,
        args.subjects,
        args.styles,
        args.subject_thr,
    )
    bg_refs = _list_background_refs(args.bg_data_root)
    if args.limit_fg is not None:
        fg_refs = fg_refs[: args.limit_fg]
    if args.limit_bg is not None:
        bg_refs = bg_refs[: args.limit_bg]
    if not fg_refs:
        raise SystemExit(
            f"no foregrounds under {args.fg_data_root}/images match filter",
        )
    if not bg_refs:
        raise SystemExit(f"no backgrounds under {args.bg_data_root}/images")

    device = select_device(args.device)
    print(f"Loading estimator {args.model!r} on {device}")
    estimator = ESTIMATORS[args.model]()
    estimator.load(device)

    neutral = Image.fromarray(
        make_textured_bg(size=args.size, seed=args.neutral_bg_seed),
        mode="RGB",
    )

    print(f"Foregrounds: {len(fg_refs)}")
    for ref in fg_refs:
        fg = prepare_foreground(args.fg_data_root / "images" / ref, args.size)
        composited = composite_on_neutral(fg, neutral)
        [raw_disp] = estimator.infer([composited])
        alpha = np.asarray(fg, dtype=np.float32)[..., 3] / 255.0
        core = trusted_core(
            alpha,
            raw_disp,
            nb_pixels_remove=args.nb_pixels_remove,
            threshold=args.alpha_threshold,
            low_pct=args.low_pct,
        )
        depth = propagate_disparity(
            raw_disp,
            alpha,
            nb_pixels_remove=args.nb_pixels_remove,
            threshold=args.alpha_threshold,
            low_pct=args.low_pct,
        )
        asset_id = _ref_to_id(ref)
        write_foreground(
            args.output,
            asset_id,
            fg,
            alpha,
            depth,
            raw_depth=raw_disp.astype(np.float32),
        )
        raw_eroded = trusted_core(
            alpha,
            raw_disp,
            args.nb_pixels_remove,
            args.alpha_threshold,
            low_pct=0.0,
        )
        p01, p99 = (float(v) for v in np.percentile(raw_disp, [1.0, 99.0]))
        write_asset_metadata(
            args.output / FOREGROUNDS / asset_id,
            {
                "estimator": args.model,
                "source_ref": ref,
                "neutral_bg_seed": args.neutral_bg_seed,
                "nb_pixels_remove": args.nb_pixels_remove,
                "alpha_threshold": args.alpha_threshold,
                "low_pct": args.low_pct,
                "raw_p01": p01,
                "raw_p99": p99,
                "core_frac": float(core.mean()),
                "n_low_outliers": int(raw_eroded.sum() - core.sum()),
                "low_confidence": bool(core.sum() < 0.002 * core.size),
            },
        )
        print(f"  fg {ref}  core_frac={float(core.mean()):.3f}")

    print(f"Backgrounds: {len(bg_refs)}")
    for ref in bg_refs:
        bg = prepare_background(
            args.bg_data_root / "images" / ref,
            args.size,
            args.bg_margin,
        )
        [bg_disp] = estimator.infer([bg])
        write_background(args.output, _ref_to_id(ref), bg, bg_disp.astype(np.float32))
        print(f"  bg {ref}")

    print(f"\nDone. Library at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
