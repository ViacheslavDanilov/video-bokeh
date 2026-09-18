#!/usr/bin/env python3
"""Build a synthetic dataset end to end, in one command.

Two stages, in order. Stage A estimates depth once per asset and writes the artifact
library; Stage B samples scenes from that library and writes sequences. Bokeh is a
separate pipeline and is not run here.

A fresh clone has everything this needs: `backend/data/magick_dev` (20 foregrounds) and
`backend/data/bg-20k_dev` (20 backgrounds) are tracked on purpose, so there is nothing to
download except the depth model, which Hugging Face caches on first use.

    uv run python scripts/build_dataset.py

That writes `backend/data/library_demo` and `backend/data/demo` with sane defaults. The
library is reused on later runs unless you pass --rebuild-library, which is the point:
Stage A is the slow one.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"


def _run(stage: str, args: list[str]) -> None:
    """Run one stage from backend/, and stop the whole script if it fails."""
    print(f"\n{'=' * 70}\n{stage}\n{'=' * 70}", flush=True)
    started = time.perf_counter()
    result = subprocess.run(
        ["uv", "run", "python", "-m", *args],
        cwd=_BACKEND,
        check=False,
    )
    if result.returncode != 0:
        sys.exit(f"\n{stage} failed with exit code {result.returncode}. Stopping.")
    print(f"\n{stage} took {time.perf_counter() - started:.1f} s")


def _summarize(dataset: Path) -> None:
    sequences = sorted((dataset / "sequences").iterdir())
    if not sequences:
        sys.exit(f"no sequences were written to {dataset}")

    print(f"\n{'=' * 70}\nWhat you got\n{'=' * 70}")
    print(f"\n{len(sequences)} sequences in {dataset.relative_to(_REPO)}/sequences\n")
    print(f"  {'sequence':<10}{'frames':>8}{'objects':>9}  streams")
    for seq in sequences:
        frames = len(list((seq / "all_in_focus").glob("*.png")))
        objects = len(list((seq / "alpha").glob("*.tif"))) and _pages(seq)
        print(
            f"  {seq.name:<10}{frames:>8}{objects:>9}  all_in_focus/ alpha/ disparity/",
        )

    total = sum(f.stat().st_size for f in dataset.rglob("*") if f.is_file())
    print(f"\n  total on disk: {total / 1024**2:.1f} MB")
    print(f"  manifest:      {(dataset / 'manifest.csv').relative_to(_REPO)}")

    print("\nLook at it:\n")
    print(f"  cd {(dataset / 'sequences').relative_to(_REPO)}")
    print('  vpv "*/all_in_focus/*.png" "*/disparity/*.png"')
    print("\n  An object that grows on screen must get brighter in the disparity pane.")
    print(
        "  vpv shows only a TIFF's first page, so read alpha with data._streams instead.",
    )
    print("\nNext, if you want bokeh:\n")
    print(
        f"  cd backend && uv run python -m data.prepare_any_to_bokeh "
        f"--data-root {dataset.relative_to(_BACKEND)}",
    )


def _pages(seq: Path) -> int:
    """Object count for a sequence, read from its first alpha frame."""
    sys.path.insert(0, str(_BACKEND / "src"))
    from data._streams import read_alpha_tiff

    return len(read_alpha_tiff(sorted((seq / "alpha").glob("*.tif"))[0]))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--fg-data-root", default="data/magick_dev")
    parser.add_argument("--bg-data-root", default="data/bg-20k_dev")
    parser.add_argument("--library", default="data/library_demo")
    parser.add_argument("--output", default="data/demo")
    parser.add_argument("--count", type=int, default=4, help="sequences to generate")
    parser.add_argument("--frames", type=int, default=24)
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-objects-min", type=int, default=1)
    parser.add_argument("--n-objects-max", type=int, default=5)
    parser.add_argument(
        "--model",
        default="da2-small",
        choices=("da2-small", "da2-base", "da2-large"),
        help="depth model for stage A. da2-large is slower and better.",
    )
    parser.add_argument(
        "--rebuild-library",
        action="store_true",
        help="rerun stage A even if the library already exists",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    library = _BACKEND / args.library
    dataset = _BACKEND / args.output

    for name, path in (
        ("foregrounds", args.fg_data_root),
        ("backgrounds", args.bg_data_root),
    ):
        if not (_BACKEND / path).exists():
            sys.exit(
                f"{name} not found at backend/{path}. A fresh clone ships "
                f"data/magick_dev and data/bg-20k_dev; see backend/README.md.",
            )

    if library.exists() and not args.rebuild_library:
        print(f"Stage A: reusing the library at backend/{args.library}", flush=True)
        print("         pass --rebuild-library to rerun it", flush=True)
    else:
        _run(
            "Stage A — build the artifact library (depth runs once per asset)",
            [
                "data.build_library",
                "--fg-data-root",
                args.fg_data_root,
                "--bg-data-root",
                args.bg_data_root,
                "--output",
                args.library,
                "--size",
                str(args.size),
                "--model",
                args.model,
            ],
        )

    _run(
        "Stage B — generate sequences from the library",
        [
            "data.generate_dataset",
            "--library-root",
            args.library,
            "--output",
            args.output,
            "--count",
            str(args.count),
            "--frames",
            str(args.frames),
            "--size",
            str(args.size),
            "--seed",
            str(args.seed),
            "--n-objects-min",
            str(args.n_objects_min),
            "--n-objects-max",
            str(args.n_objects_max),
        ],
    )

    _summarize(dataset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
