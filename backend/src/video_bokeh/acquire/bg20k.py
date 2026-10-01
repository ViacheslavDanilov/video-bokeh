#!/usr/bin/env python3
"""Download the BG-20k dataset via kagglehub, whole or as a sample one file at a time.

Source: https://www.kaggle.com/datasets/nguyenquocdungk16hl/bg-20o

Usage:
    uv run python -m video_bokeh.acquire.bg20k --output backend/data/bg-20k
    uv run python -m video_bokeh.acquire.bg20k --output data/bg-20k_dev --count 30 --seed 11

With ``--count`` nothing is downloaded in bulk. The split lists are read, shuffled with
``--seed``, and backgrounds are fetched one file at a time until the pool at ``--output``
holds ``--count``, laid out as ``images/<split>/<file>`` with a ``metadata.csv``. What the
pool already holds stays, first and as it is, so a pool only grows, and a larger count
extends the same order a run straight to it would have taken.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

KAGGLE_DATASET = "nguyenquocdungk16hl/bg-20o"

#: The upload splits BG-20k into folders 1 to 7, and nothing says which file is in which,
#: so each is tried in turn.
_SHARDS = range(1, 8)
#: Both split lists sit in the first folder.
_LISTS = {"train": "1/BG-20k/train.txt", "testval": "1/BG-20k/testval.txt"}

#: Fetches one file of the dataset into a directory and returns where it landed.
Download = Callable[[str, str], str]


def _read_pool(pool: Path) -> list[tuple[str, str]]:
    metadata = pool / "metadata.csv"
    if not metadata.is_file():
        return []
    with metadata.open(encoding="utf-8", newline="") as f:
        return [(r["filename"], r["split"]) for r in csv.DictReader(f)]


def _write_pool(pool: Path, rows: list[tuple[str, str]]) -> None:
    with (pool / "metadata.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "split"])
        writer.writerows(rows)


def _fetch_background(
    name: str,
    split: str,
    download: Download,
    scratch: str,
) -> str | None:
    for shard in _SHARDS:
        try:
            return download(f"{shard}/BG-20k/{split}/{name}", scratch)
        except Exception:
            # Not in this shard: the download refuses a path the upload does not have.
            continue
    return None


def sample_pool(pool: Path, count: int, seed: int, download: Download) -> None:
    """Grow the background pool at ``pool`` to ``count``, fetching one file at a time."""
    rows = _read_pool(pool)
    if len(rows) >= count:
        return
    with tempfile.TemporaryDirectory() as scratch:
        candidates = sorted(
            (name, split)
            for split, listing in _LISTS.items()
            for name in Path(download(listing, scratch)).read_text().split()
        )
        # A full shuffle, so the order does not depend on how many are drawn from it.
        random.Random(seed).shuffle(candidates)
        held = set(rows)
        for name, split in candidates:
            if len(rows) >= count:
                break
            if (name, split) in held:
                continue
            fetched = _fetch_background(name, split, download, scratch)
            if fetched is None:
                print(f"  SKIP {split}/{name}: in no shard")
                continue
            dest = pool / "images" / split / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(fetched, dest)
            rows.append((name, split))
            print(f"  OK   {split}/{name}")
    pool.mkdir(parents=True, exist_ok=True)
    _write_pool(pool, rows)
    print(f"\n{len(rows)} backgrounds in {pool}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="grow the pool at --output to this many, one file at a time",
    )
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    if args.count is not None:
        # Each file goes to a scratch directory and is copied in, so the pool holds images
        # and metadata only, not kagglehub's own bookkeeping.
        import kagglehub

        def _download(path: str, output_dir: str) -> str:
            return kagglehub.dataset_download(
                KAGGLE_DATASET,
                path=path,
                output_dir=output_dir,
            )

        sample_pool(args.output, args.count, args.seed, _download)
        return 0

    os.environ["KAGGLEHUB_CACHE"] = str(args.output.resolve())

    import kagglehub  # noqa: E402 — must be imported after KAGGLEHUB_CACHE is set

    path = kagglehub.dataset_download(KAGGLE_DATASET)
    print(f"Path to dataset files: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
