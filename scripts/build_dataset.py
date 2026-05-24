#!/usr/bin/env python3
"""Build a synthetic dataset end-to-end.

Runs four stages in order, then prints the any-to-bokeh command for the user
to run by hand. Halts on the first non-zero exit. Always re-runs every stage
— no skip-if-output-exists logic.

Stages:
    1. data.classify_clip        — score MAGICK foregrounds with CLIP.
                                   Writes <fg-data-root>/predictions.csv.
    2. data.generate_sequences   — render synthetic sequences with motion.
                                   Writes manifest.csv + frames into --output.
    3. data.estimate_disparity   — bake per-frame disparity GT with the
                                   chosen depth model. Writes
                                   <output>/sequences/<id>/disparity/*.tif.
    4. data.prepare_any_to_bokeh — convert to the any-to-bokeh layout under
                                   <a2b-root>/demo_dataset and write
                                   <a2b-root>/csv_file/<dataset-name>.csv.

Step 5 (any-to-bokeh inference) lives in a different Python env under
backend/third_party/any-to-bokeh; this orchestrator just prints the command.

Assumes the foreground (MAGICK) and background (BG-20k) datasets are already
downloaded under their respective --fg-data-root and --bg-data-root paths.

Usage:
    uv run python scripts/build_dataset.py \\
        --fg-data-root backend/data/magick \\
        --bg-data-root backend/data/bg-20k_dev \\
        --output       backend/data/synth_dev_new \\
        --count        10 \\
        --seed         0

    # Override depth model and filter thresholds:
    uv run python scripts/build_dataset.py \\
        --fg-data-root backend/data/magick \\
        --bg-data-root backend/data/bg-20k_dev \\
        --output       backend/data/synth_dev_new \\
        --count        10 \\
        --depth-model  da2-base \\
        --subject-thr  0.60

    # Skip stages that are already done (predictions.csv + sequences exist):
    uv run python scripts/build_dataset.py \\
        --fg-data-root backend/data/magick \\
        --bg-data-root backend/data/bg-20k_dev \\
        --output       backend/data/synth_dev_new \\
        --count        10 \\
        --skip         classify,generate
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

STAGE_NAMES: tuple[str, ...] = ("classify", "generate", "disparity", "prepare")
DEFAULT_SUBJECTS = "person,animal,plant,food,object"
DEFAULT_STYLES = "photo,render"
DEFAULT_SUBJECT_THR = 0.50
DEFAULT_STYLE_THR = 0.00
DEFAULT_DEPTH_MODEL = "da2-large"
DEFAULT_A2B_ROOT = "backend/third_party/any-to-bokeh"
DEFAULT_BATCH_SIZE = 64
DEFAULT_DEVICE = "auto"


def run_stage(label: str, cmd: list[str], skip: set[str], short: str) -> None:
    if short in skip:
        print(f"\n  ── [{label}] SKIPPED (--skip {short})")
        return
    print(f"\n  ── [{label}] " + "─" * (70 - len(label)))
    print(f"  $ {' '.join(cmd)}")
    start = time.time()
    result = subprocess.run(cmd, check=False)
    mins, secs = divmod(int(time.time() - start), 60)
    if result.returncode != 0:
        print(f"  [{label}] FAILED after {mins}m {secs}s (exit {result.returncode})")
        sys.exit(result.returncode)
    print(f"  [{label}] done in {mins}m {secs}s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="End-to-end synthetic dataset build pipeline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Required paths
    parser.add_argument(
        "--fg-data-root",
        type=Path,
        required=True,
        help="MAGICK foregrounds root (must contain metadata.csv and images/).",
    )
    parser.add_argument(
        "--bg-data-root",
        type=Path,
        required=True,
        help="BG-20k backgrounds root (must contain images/).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Where the rendered dataset lands (sequences/ + manifest.csv).",
    )
    # Sequence generation
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of sequences to render.",
    )
    parser.add_argument("--seed", type=int, default=0, help="Manifest RNG seed.")
    # Foreground filter (passed through to generate_sequences)
    parser.add_argument(
        "--subjects",
        default=DEFAULT_SUBJECTS,
        help="Comma-separated subject classes to keep.",
    )
    parser.add_argument(
        "--styles",
        default=DEFAULT_STYLES,
        help="Comma-separated style classes to keep.",
    )
    parser.add_argument(
        "--subject-thr",
        type=float,
        default=DEFAULT_SUBJECT_THR,
        help="Minimum keep_confidence to keep a foreground.",
    )
    parser.add_argument(
        "--style-thr",
        type=float,
        default=DEFAULT_STYLE_THR,
        help="Minimum top_style_score to keep a foreground (0 disables).",
    )
    # Depth
    parser.add_argument(
        "--depth-model",
        default=DEFAULT_DEPTH_MODEL,
        help="Depth estimator key (e.g. da2-small, da2-base, da2-large).",
    )
    # a2b layout
    parser.add_argument(
        "--a2b-root",
        type=Path,
        default=Path(DEFAULT_A2B_ROOT),
        help="Vendored any-to-bokeh root.",
    )
    parser.add_argument(
        "--dataset-name",
        default=None,
        help="Name under demo_dataset/ and csv_file/. Default: --output basename.",
    )
    # Compute
    parser.add_argument(
        "--device",
        default=DEFAULT_DEVICE,
        choices=["auto", "cuda", "mps", "cpu"],
        help="Device for CLIP and depth models.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="CLIP batch size for classify_clip.",
    )
    # Stage selection
    parser.add_argument(
        "--skip",
        default="",
        help=(
            "Comma-separated stages to skip. "
            f"Valid names: {','.join(STAGE_NAMES)}. "
            "Example: --skip classify,generate (resume from disparity)."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_name = args.dataset_name or args.output.name
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    unknown = skip - set(STAGE_NAMES)
    if unknown:
        print(f"  ERROR: unknown stage(s) in --skip: {','.join(sorted(unknown))}")
        print(f"  Valid stage names: {','.join(STAGE_NAMES)}")
        return 2
    pipeline_start = time.time()

    print("  Synthetic dataset build")
    print(f"    fg-data-root : {args.fg_data_root}")
    print(f"    bg-data-root : {args.bg_data_root}")
    print(f"    output       : {args.output}")
    print(f"    count        : {args.count}")
    print(f"    depth-model  : {args.depth_model}")
    print(f"    a2b dataset  : {dataset_name}")
    if skip:
        print(f"    skipping     : {','.join(s for s in STAGE_NAMES if s in skip)}")

    # 1) CLIP classification on foregrounds
    run_stage(
        "1/4 classify_clip",
        [
            "uv",
            "run",
            "python",
            "-m",
            "data.classify_clip",
            "--data-root",
            str(args.fg_data_root),
            "--device",
            args.device,
            "--batch-size",
            str(args.batch_size),
        ],
        skip,
        "classify",
    )

    # 2) Render synthetic sequences
    run_stage(
        "2/4 generate_sequences",
        [
            "uv",
            "run",
            "python",
            "-m",
            "data.generate_sequences",
            "--fg-data-root",
            str(args.fg_data_root),
            "--bg-data-root",
            str(args.bg_data_root),
            "--output",
            str(args.output),
            "--count",
            str(args.count),
            "--seed",
            str(args.seed),
            "--subjects",
            args.subjects,
            "--styles",
            args.styles,
            "--subject-thr",
            str(args.subject_thr),
            "--style-thr",
            str(args.style_thr),
        ],
        skip,
        "generate",
    )

    # 3) Bake disparity GT
    run_stage(
        "3/4 estimate_disparity",
        [
            "uv",
            "run",
            "python",
            "-m",
            "data.estimate_disparity",
            "--data-root",
            str(args.output),
            "--fg-data-root",
            str(args.fg_data_root),
            "--bg-data-root",
            str(args.bg_data_root),
            "--model",
            args.depth_model,
            "--device",
            args.device,
        ],
        skip,
        "disparity",
    )

    # 4) Convert to any-to-bokeh layout
    run_stage(
        "4/4 prepare_any_to_bokeh",
        [
            "uv",
            "run",
            "python",
            "-m",
            "data.prepare_any_to_bokeh",
            "--data-root",
            str(args.output),
            "--a2b-root",
            str(args.a2b_root),
            "--dataset-name",
            dataset_name,
        ],
        skip,
        "prepare",
    )

    total_mins, total_secs = divmod(int(time.time() - pipeline_start), 60)
    print(f"\n  Pipeline finished in {total_mins}m {total_secs}s.")
    print("  Next step: run any-to-bokeh by hand:")
    print(f"    cd {args.a2b_root}")
    print(
        f"    python test/inference_demo.py --val_csv_path csv_file/{dataset_name}.csv",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
