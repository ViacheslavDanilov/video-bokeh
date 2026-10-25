"""Draw the test foregrounds once, so that the fixed set shows objects training never sees.

    python -m video_bokeh.library.split --library-root data/library/da2-large \\
        --predictions data/magick/predictions.csv

MAGICK has no split of its own. This takes ``--fraction`` of a library's foregrounds,
the same fraction of each subject CLIP gave them in ``--predictions``, so the rarer
subjects, such as animals and plants, are in the test split in their share and not by
chance. The draw is seeded by ``--seed`` and the subject, and it writes the ids, sorted,
to the file ``video_bokeh.core._split`` reads. Backgrounds need no draw: they follow
BG-20k's split.

The list was drawn once, from the published library, and is tracked. Drawing it again
with other arguments, or from another library, changes the fixed set and every sequence
a seed names.
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

from video_bokeh.core._library import list_foregrounds
from video_bokeh.core._split import TEST_FOREGROUNDS

FRACTION = 0.1
SEED = 0
OUTPUT = Path(__file__).resolve().parents[1] / "core" / TEST_FOREGROUNDS


def page_id(asset_id: str) -> str:
    """The MAGICK page id a foreground's id ends in, after its folder."""
    return asset_id.rsplit("__", 1)[-1]


def draw(
    foreground_ids: list[str],
    subjects: dict[str, str],
    fraction: float = FRACTION,
    seed: int = SEED,
) -> list[str]:
    """``fraction`` of the ids of each subject, rounded, sorted.

    ``subjects`` maps a MAGICK page id to the subject CLIP gave it.
    """
    if not 0 < fraction < 1:
        raise ValueError(f"fraction must be between 0 and 1, not {fraction}")
    missing = [i for i in foreground_ids if page_id(i) not in subjects]
    if missing:
        raise ValueError(
            f"{len(missing)} foregrounds have no subject, {missing[0]} first",
        )
    by_subject: dict[str, list[str]] = defaultdict(list)
    for asset_id in sorted(foreground_ids):
        by_subject[subjects[page_id(asset_id)]].append(asset_id)
    test: list[str] = []
    for subject in sorted(by_subject):
        ids = by_subject[subject]
        rng = random.Random(f"split:{seed}:{subject}")
        test += rng.sample(ids, round(len(ids) * fraction))
    return sorted(test)


def read_subjects(predictions: Path) -> dict[str, str]:
    """Each page id's ``top_subject`` in a predictions file of ``acquire.classify``."""
    with predictions.open(encoding="utf-8", newline="") as f:
        return {row["page_id"]: row["top_subject"] for row in csv.DictReader(f)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, required=True)
    parser.add_argument(
        "--predictions",
        type=Path,
        required=True,
        help="the CLIP predictions of the library's MAGICK pool",
    )
    parser.add_argument("--fraction", type=float, default=FRACTION)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    foregrounds = list_foregrounds(args.library_root)
    if not foregrounds:
        parser.error(f"no foregrounds in {args.library_root}")
    try:
        test = draw(
            foregrounds, read_subjects(args.predictions), args.fraction, args.seed
        )
    except ValueError as exc:
        parser.error(str(exc))
    args.output.write_text("".join(f"{i}\n" for i in test), encoding="utf-8")
    print(f"{len(test)} of {len(foregrounds)} foregrounds in the test split")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
