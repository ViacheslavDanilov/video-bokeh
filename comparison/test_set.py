#!/usr/bin/env python3
"""Write the comparison's test set: 32 sequences of any scene and 8 of night scenes, in one root.

Runs in the backend's environment, from ``backend/``, with the render extra for the bokeh:

    cd backend && uv run --extra render python ../comparison/test_set.py --output data/test_set

Every sequence has 24 frames of 1024 pixels, its layers and our bokeh, which is what
``run_all.sh`` needs. ``any-01`` to ``any-32`` take the first 32 seeds from 1,000,000 that can
be placed, far from the seeds a dataset is written with. ``night-01`` to ``night-08`` take eight
seeds whose background is a night scene with small lights: dark on average, with little bright
area, in many small spots, where a bokeh renderer shows the most. They were found by scanning
the backgrounds of seeds below 50,000 in the ``da2-large`` library and kept only where the
background, looked at, is a night scene; each has a different background. ``manifest.csv``
and ``objects.csv`` hold every sequence, as a Stage B run writes them.

``<output>/night`` is a second data root whose sequences link to the night ones, so that
``score.py`` and ``summary.py`` can report them apart without rendering them again.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import shutil
from pathlib import Path

from video_bokeh.scenes.generate import generate_dataset

FRAMES = 24
SIZE = 1024
ANY_FROM = 1_000_000
ANY_COUNT = 32
NIGHT_SEEDS = (9361, 14292, 20512, 23969, 42581, 15881, 20133, 19177)


def _read_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def build(
    library_root: Path,
    output: Path,
    *,
    frames: int = FRAMES,
    size: int = SIZE,
    any_from: int = ANY_FROM,
    any_count: int = ANY_COUNT,
    night_seeds: tuple[int, ...] = NIGHT_SEEDS,
) -> dict[str, int]:
    """Write the test set under ``output`` and return each sequence's seed by its name."""
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"{output} is not empty: write the test set into a new folder")
    staging = output / ".staging"
    (output / "sequences").mkdir(parents=True, exist_ok=True)
    tables: dict[str, tuple[list[str], list[list[str]]]] = {}
    seeds: dict[str, int] = {}

    def take(seed: int, name: str) -> bool:
        shutil.rmtree(staging, ignore_errors=True)
        written = generate_dataset(
            library_root, staging, 1, frames, size, seed, layers=True, bokeh=True
        )
        if not written:
            return False
        (staging / "sequences" / "0001").rename(output / "sequences" / name)
        for table in ("manifest.csv", "objects.csv"):
            header, rows = _read_rows(staging / table)
            kept = tables.setdefault(table, (header, []))[1]
            kept.extend([name, *row[1:]] for row in rows)
        seeds[name] = seed
        return True

    candidates = itertools.count(any_from)
    for k in range(1, any_count + 1):
        while not take(next(candidates), f"any-{k:02d}"):
            pass
    for k, seed in enumerate(night_seeds, start=1):
        if not take(seed, f"night-{k:02d}"):
            raise SystemExit(f"night seed {seed} cannot be placed")
    shutil.rmtree(staging)

    night = output / "night" / "sequences"
    night.mkdir(parents=True)
    for name in seeds:
        if name.startswith("night-"):
            (night / name).symlink_to(Path("../..") / "sequences" / name)
    for table in ("objects.csv", "manifest.csv"):  # the manifest last, as Stage B does
        header, rows = tables[table]
        with (output / table).open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows([header, *rows])
    return seeds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--library-root", type=Path, default=Path("data/library/da2-large")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    for name, seed in build(args.library_root, args.output).items():
        print(f"{name}  seed={seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
