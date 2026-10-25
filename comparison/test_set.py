#!/usr/bin/env python3
"""Write the comparison's test set: 32 sequences of any scene and 8 of night scenes, in one root.

Runs in the backend's environment, from ``backend/``, with the render extra for the bokeh:

    cd backend && uv run --extra render python ../comparison/test_set.py --output data/test_set

Every sequence has 24 frames of 1024 pixels, one or two objects, its layers and our bokeh,
which is what ``run_all.sh`` needs. With few objects, a box on an object's edge shows one
transition, between the object and what lies behind it.

``any-01`` to ``any-32`` take the first 32 seeds from 1,000,000 that can be placed and whose
background has detail, far from the seeds a dataset is written with. A background has detail
when its gray levels, at 512 pixels, differ from a Gaussian blur of radius 2 by 3 levels or
more on average: on a flat one, such as a white wall, no renderer's blur shows. About one
background in seven of the ``da2-large`` library falls below that.

``night-01`` to ``night-08`` take eight seeds whose background is a night scene with small
lights: dark on average, with little bright area, in many small spots, where a bokeh renderer
shows the most. Each background was looked at and is a different one; each seed is the first
from 1,000 that draws it with one or two objects. ``manifest.csv`` and ``objects.csv`` hold
every sequence, as a Stage B run writes them.

``<output>/night`` is a second data root whose sequences link to the night ones, so that
``score.py`` and ``summary.py`` can report them apart without rendering them again.

Every sequence draws from all of the library's assets, train and test, because the set was
drawn before the library had splits and its seeds name those scenes only so.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from video_bokeh.core._library import BACKGROUNDS
from video_bokeh.core._split import ALL
from video_bokeh.scenes.generate import generate_dataset

FRAMES = 24
SIZE = 1024
ANY_FROM = 1_000_000
ANY_COUNT = 32
N_OBJECTS_MAX = 2
MIN_DETAIL = 3.0
NIGHT_SEEDS = (1559, 3033, 41400, 2170, 37036, 8836, 2881, 10482)


def _read_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def detail(library_root: Path, background: str) -> float:
    """How much a blur would change a background: the mean absolute difference, in gray
    levels at 512 pixels, from its Gaussian blur of radius 2."""
    with Image.open(library_root / BACKGROUNDS / background / "rgb.png") as im:
        gray = im.convert("L").resize((512, 512), Image.Resampling.BILINEAR)
        blurred = gray.filter(ImageFilter.GaussianBlur(2))
    return float(
        np.abs(np.asarray(gray, np.float32) - np.asarray(blurred, np.float32)).mean()
    )


def build(
    library_root: Path,
    output: Path,
    *,
    frames: int = FRAMES,
    size: int = SIZE,
    any_from: int = ANY_FROM,
    any_count: int = ANY_COUNT,
    night_seeds: tuple[int, ...] = NIGHT_SEEDS,
    n_objects_max: int = N_OBJECTS_MAX,
    min_detail: float = MIN_DETAIL,
) -> dict[str, int]:
    """Write the test set under ``output`` and return each sequence's seed by its name."""
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"{output} is not empty: write the test set into a new folder")
    staging = output / ".staging"
    (output / "sequences").mkdir(parents=True, exist_ok=True)
    tables: dict[str, tuple[list[str], list[list[str]]]] = {}
    seeds: dict[str, int] = {}

    def take(seed: int, name: str, need_detail: bool) -> bool:
        shutil.rmtree(staging, ignore_errors=True)
        written = generate_dataset(
            library_root,
            staging,
            1,
            frames,
            size,
            seed,
            n_objects_max=n_objects_max,
            layers=True,
            bokeh=True,
            # The published set was drawn before the library had splits, from every
            # asset, so its seeds name those scenes only in `all`.
            split=ALL,
        )
        if not written:
            return False
        header, rows = _read_rows(staging / "manifest.csv")
        background = rows[0][header.index("background")]
        if need_detail and detail(library_root, background) < min_detail:
            print(f"  skip  seed={seed}  flat background {background}")
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
        while not take(next(candidates), f"any-{k:02d}", need_detail=True):
            pass
    for k, seed in enumerate(night_seeds, start=1):
        if not take(seed, f"night-{k:02d}", need_detail=False):
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
