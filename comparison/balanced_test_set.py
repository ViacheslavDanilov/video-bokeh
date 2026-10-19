#!/usr/bin/env python3
"""Write the balanced test set: 60 plain sequences and 60 with hard edges, in one root.

Runs in the backend's environment, from ``backend/``, with the render extra for the bokeh and
the library extra for scipy:

    cd backend && uv run --extra render --extra library python ../comparison/balanced_test_set.py \
        --output data/balanced_test_set

Every sequence has 24 frames of 1024 pixels, one or two objects, its layers and our bokeh,
which is what ``run_all.sh`` needs. Every sequence is kept or passed over by a rule; none was
chosen by looking at it.

``plain-01`` to ``plain-60`` are drawn as ``test_set.py`` draws its ``any`` sequences: the
first 60 seeds from 4,000,000 that can be placed and whose background has detail, with any
object of the library.

``hair-01`` to ``hair-15``, and 15 each of ``fire``, ``smoke`` and ``fine``, have a hard edge
in focus. Their objects come from ``hard_edge_objects.txt``, 107 library foregrounds picked by
hand for their edges, each with its category. A light edge shows against a dark background
and a dark one against a light background, so each category's objects are split into pools:

- an object whose edge is light, its mean luminance over a band 8 pixels deep inside its
  alpha's edge 0.5 or more, and every fire and smoke object, goes on a dark background, of mean luminance
  below 0.25; the others go on a light one, above 0.65;
- either kind of background has detail of 3 or more, as the plain ones do.

Each category takes seeds from its own start, 4,100,000 for hair, 4,200,000 fire, 4,300,000
smoke and 4,400,000 fine detail. A category with objects of both kinds draws on the dark pool
on an even seed and on the light pool on an odd one. A seed is kept when its sequence can be
placed, its focus, as ``bokeh/focus.json`` records it, is on an object, and that object's edge
passes two thresholds measured on the all-in-focus frames:

- contrast of 0.15 or more: the luminance, in ``[0, 1]``, 6 pixels deep inside the edge of
  the object in focus against 8 pixels out where no object is, with what a nearer object
  hides taken away, as ``review.py`` does; the median over every third frame;
- share of 0.01 or more: the median part of the frame that the object in focus shows.

A frame counts toward both medians when the object shows on 0.005 of it or more and either
band has 200 pixels or more. An object leaves its pool once it is in focus in two kept
sequences, so that no few objects fill a category, or once it has been in focus in three
sequences passed over, so that an edge that never shows does not hold up the run. A hard
seed draws from the objects left in its pool at that point, so it writes its sequence again
only within the whole run.

``manifest.csv`` and ``objects.csv`` hold every sequence, as a Stage B run writes them, and
``selection.csv`` each one's group, category, seed, number of objects and their ids, the object
in focus, its background, the side of that background, and the contrast and share. ``plain``, ``hard``,
``hair``, ``fire``, ``smoke`` and ``fine`` beside ``sequences`` are data roots whose sequences
link to their own, so that ``score.py`` and ``summary.py`` can report each subset apart
without rendering it again.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image
from review import focus_alpha
from scipy import ndimage
from test_set import _read_rows, detail

from video_bokeh.core._library import (
    BACKGROUNDS,
    FOREGROUNDS,
    list_backgrounds,
)
from video_bokeh.core._streams import read_alpha_tiff, read_paint_order
from video_bokeh.scenes.generate import generate_dataset

FRAMES = 24
SIZE = 1024
N_OBJECTS_MAX = 2
PLAIN_FROM = 4_000_000
PLAIN_COUNT = 60
CATEGORIES = ("hair", "fire", "smoke", "fine")
HARD_FROM = {
    "hair": 4_100_000,
    "fire": 4_200_000,
    "smoke": 4_300_000,
    "fine": 4_400_000,
}
HARD_COUNT = 15
#: Categories whose edge is light whatever its luminance says: a flame, a wisp of smoke.
ALWAYS_LIGHT = ("fire", "smoke")
#: An object edge at least this luminous is light.
LIGHT_EDGE = 0.5
EDGE_DEPTH = 8
#: A dark background is below the first mean luminance, a light one above the second.
DARK_BELOW = 0.25
LIGHT_ABOVE = 0.65
MIN_DETAIL = 3.0
MIN_CONTRAST = 0.15
MIN_SHARE = 0.01
MAX_FOCUS = 2
MAX_PASSED = 3
OBJECTS = Path(__file__).with_name("hard_edge_objects.txt")

#: The weights of luminance, from RGB.
_LUMA = np.array([0.299, 0.587, 0.114], np.float32)
#: How the contrast is measured: every third frame, 6 pixels in and 8 out, in frames where
#: the object shows at least this share and each band has at least this many pixels.
_EVERY, _INNER, _OUTER, _MIN_FRAME_SHARE, _MIN_PIXELS = 3, 6, 8, 0.005, 200


def read_objects(path: Path) -> dict[str, str]:
    """Each picked foreground's category, from lines ``<foreground id> <category>``."""
    picked = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            asset, category = line.split()
            if category not in CATEGORIES:
                raise SystemExit(f"{path}: {asset} has no category of {CATEGORIES}")
            picked[asset] = category
    return picked


def background_stats(library_root: Path, background: str) -> tuple[float, float]:
    """A background's mean luminance in ``[0, 1]``, at 512 pixels, and its detail, as
    ``test_set.detail`` measures it."""
    with Image.open(library_root / BACKGROUNDS / background / "rgb.png") as im:
        gray = im.convert("L").resize((512, 512), Image.Resampling.BILINEAR)
    lum = float(np.asarray(gray, np.float32).mean() / 255)
    return lum, detail(library_root, background)


def edge_luminance(library_root: Path, foreground: str) -> float:
    """The mean luminance, in ``[0, 1]``, of the ``EDGE_DEPTH`` pixels inside an object's
    edge, where its alpha is above one half."""
    base = library_root / FOREGROUNDS / foreground
    if not base.is_dir():
        raise SystemExit(f"{foreground} is not a foreground of {library_root}")
    with Image.open(base / "alpha.png") as im:
        solid = np.asarray(im.convert("L"), np.float32) / 255 > 0.5
    with Image.open(base / "rgb.png") as im:
        lum = np.asarray(im.convert("RGB"), np.float32) / 255 @ _LUMA
    edge = solid & ~ndimage.binary_erosion(solid, iterations=EDGE_DEPTH)
    if not edge.any():
        raise SystemExit(f"{foreground} has no pixel of alpha above one half")
    return float(lum[edge].mean())


def pools(
    library_root: Path, picked: dict[str, str]
) -> dict[str, list[tuple[str, list[str], list[str]]]]:
    """Per category, its pools: the side, ``dark`` or ``light``, of their backgrounds, the
    category's objects that show against them, and those backgrounds, sorted."""
    ids = list_backgrounds(library_root)
    with ThreadPoolExecutor() as pool:
        measured = pool.map(lambda b: background_stats(library_root, b), ids)
        stats = dict(zip(ids, measured, strict=True))
    backs = {
        "dark": [
            b for b, (lum, d) in stats.items() if lum < DARK_BELOW and d >= MIN_DETAIL
        ],
        "light": [
            b for b, (lum, d) in stats.items() if lum > LIGHT_ABOVE and d >= MIN_DETAIL
        ],
    }
    out: dict[str, list[tuple[str, list[str], list[str]]]] = {}
    for category in CATEGORIES:
        sides: dict[str, list[str]] = {"dark": [], "light": []}
        for asset in sorted(a for a, c in picked.items() if c == category):
            light = (
                category in ALWAYS_LIGHT
                or edge_luminance(library_root, asset) >= LIGHT_EDGE
            )
            sides["dark" if light else "light"].append(asset)
        out[category] = [(s, sides[s], backs[s]) for s in ("dark", "light") if sides[s]]
        for side, _, bgs in out[category]:
            if not bgs:
                raise SystemExit(f"{category}: no {side} background with detail")
    return out


def edge_contrast(seq: Path, focus: int) -> tuple[float, float] | None:
    """The contrast across the edge of the object in focus and its share of the frame, the
    medians over every third frame; None when no frame shows enough of either side."""
    frames = sorted(p.stem for p in (seq / "all_in_focus").glob("*.png"))
    orders = dict(
        zip(frames, read_paint_order(seq / "layers" / "paint_order.json"), strict=True)
    )
    contrasts, shares = [], []
    for frame in frames[::_EVERY]:
        pages = read_alpha_tiff(seq / "alpha" / f"{frame}.tif")
        alpha, _ = focus_alpha(pages, focus, orders[frame])
        solid = alpha > 0.5
        share = float(solid.mean())
        if share < _MIN_FRAME_SHARE:
            continue
        inner = solid & ~ndimage.binary_erosion(solid, iterations=_INNER)
        outer = ndimage.binary_dilation(solid, iterations=_OUTER) & (
            np.max(pages, axis=0) < 0.05
        )
        if inner.sum() < _MIN_PIXELS or outer.sum() < _MIN_PIXELS:
            continue
        with Image.open(seq / "all_in_focus" / f"{frame}.png") as im:
            lum = np.asarray(im.convert("RGB"), np.float32) / 255 @ _LUMA
        contrasts.append(abs(float(lum[inner].mean() - lum[outer].mean())))
        shares.append(share)
    if not contrasts:
        return None
    return float(np.median(contrasts)), float(np.median(shares))


def _link(
    root: Path, library_root: Path, foregrounds: list[str], backgrounds: list[str]
):
    """A library of links to some of another's assets."""
    shutil.rmtree(root, ignore_errors=True)
    for kind, ids in ((FOREGROUNDS, foregrounds), (BACKGROUNDS, backgrounds)):
        (root / kind).mkdir(parents=True)
        for asset in ids:
            (root / kind / asset).symlink_to((library_root / kind / asset).resolve())


def build(
    library_root: Path,
    output: Path,
    *,
    objects: Path = OBJECTS,
    frames: int = FRAMES,
    size: int = SIZE,
    plain_from: int = PLAIN_FROM,
    plain_count: int = PLAIN_COUNT,
    hard_from: dict[str, int] = HARD_FROM,
    hard_count: int = HARD_COUNT,
    n_objects_max: int = N_OBJECTS_MAX,
    min_detail: float = MIN_DETAIL,
    min_contrast: float = MIN_CONTRAST,
    min_share: float = MIN_SHARE,
    max_focus: int = MAX_FOCUS,
    max_passed: int = MAX_PASSED,
) -> list[dict[str, str]]:
    """Write the test set under ``output`` and return its rows of ``selection.csv``."""
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"{output} is not empty: write the test set into a new folder")
    hard_pools = pools(library_root, read_objects(objects))  # a bad list fails early
    staging, linked = output / ".staging", output / ".pool"
    (output / "sequences").mkdir(parents=True, exist_ok=True)
    tables: dict[str, tuple[list[str], list[list[str]]]] = {}
    selection: list[dict[str, str]] = []

    def take(library: Path, seed: int) -> tuple[dict[str, str], list[str]] | None:
        """Write one seed's sequence into staging: its manifest row and its objects."""
        shutil.rmtree(staging, ignore_errors=True)
        if not generate_dataset(
            library,
            staging,
            1,
            frames,
            size,
            seed,
            n_objects_max=n_objects_max,
            layers=True,
            bokeh=True,
        ):
            return None
        header, rows = _read_rows(staging / "manifest.csv")
        _, objs = _read_rows(staging / "objects.csv")
        return dict(zip(header, rows[0], strict=True)), [row[2] for row in objs]

    def measure() -> tuple[int | None, float | None, float | None]:
        seq = staging / "sequences" / "0001"
        record = json.loads((seq / "bokeh" / "focus.json").read_text(encoding="utf-8"))
        focus = record.get("object")
        edge = None if focus is None else edge_contrast(seq, focus)
        return focus, *(edge or (None, None))

    def keep(
        name: str, group: str, category: str, side: str, row: dict, fgs, focus, edge
    ):
        (staging / "sequences" / "0001").rename(output / "sequences" / name)
        for table in ("manifest.csv", "objects.csv"):
            header, rows = _read_rows(staging / table)
            kept = tables.setdefault(table, (header, []))[1]
            kept.extend([name, *r[1:]] for r in rows)
        contrast, share = edge
        selection.append(
            {
                "name": name,
                "group": group,
                "category": category,
                "seed": row["seed"],
                "n_objects": row["n_objects"],
                "objects": ";".join(fgs),
                "focus": "" if focus is None else str(focus),
                "focus_fg": "" if focus is None else fgs[focus],
                "background": row["background"],
                "side": side,
                "contrast": "" if contrast is None else f"{contrast:.4f}",
                "share": "" if share is None else f"{share:.4f}",
            }
        )
        print(f"  keep  {name}  seed={row['seed']}", flush=True)

    plain = itertools.count(plain_from)
    for k in range(1, plain_count + 1):
        while True:
            seed = next(plain)
            taken = take(library_root, seed)
            if taken is None:
                continue
            row, fgs = taken
            if detail(library_root, row["background"]) < min_detail:
                print(f"  skip  seed={seed}  flat background {row['background']}")
                continue
            focus, contrast, share = measure()
            keep(
                f"plain-{k:02d}", "plain", "any", "", row, fgs, focus, (contrast, share)
            )
            break

    used: Counter[str] = Counter()
    passed: Counter[str] = Counter()
    for category, sides in hard_pools.items():
        seeds = itertools.count(hard_from[category])
        for k in range(1, hard_count + 1):
            while True:
                left = [
                    (
                        side,
                        [
                            f
                            for f in fgs
                            if used[f] < max_focus and passed[f] < max_passed
                        ],
                        bgs,
                    )
                    for side, fgs, bgs in sides
                ]
                if not any(fgs for _, fgs, _ in left):
                    raise SystemExit(
                        f"{category}: every object has been in focus as often as allowed, "
                        f"with {k - 1} sequences kept of {hard_count}"
                    )
                seed = next(seeds)
                side, fgs_left, bgs = left[seed % len(left)]
                if not fgs_left:
                    continue
                _link(linked, library_root, fgs_left, bgs)
                taken = take(linked, seed)
                if taken is None:
                    continue
                row, fgs = taken
                focus, contrast, share = measure()
                if focus is None:
                    print(f"  skip  seed={seed}  no object in focus")
                    continue
                if contrast is None or share is None:
                    passed[fgs[focus]] += 1
                    print(f"  skip  seed={seed}  no edge in focus to measure")
                    continue
                if contrast < min_contrast or share < min_share:
                    passed[fgs[focus]] += 1
                    print(
                        f"  skip  seed={seed}  contrast {contrast:.3f}  share {share:.4f}"
                    )
                    continue
                used[fgs[focus]] += 1
                keep(
                    f"{category}-{k:02d}",
                    "hard",
                    category,
                    side,
                    row,
                    fgs,
                    focus,
                    (contrast, share),
                )
                break
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(linked, ignore_errors=True)

    for subset in ("plain", "hard", *CATEGORIES):
        root = output / subset / "sequences"
        root.mkdir(parents=True)
        for row in selection:
            if subset in (row["group"], row["category"]):
                (root / row["name"]).symlink_to(
                    Path("../..") / "sequences" / row["name"]
                )
    with (output / "selection.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(selection[0]))
        writer.writeheader()
        writer.writerows(selection)
    for table in ("objects.csv", "manifest.csv"):  # the manifest last, as Stage B does
        header, rows = tables[table]
        with (output / table).open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows([header, *rows])
    return selection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--library-root", type=Path, default=Path("data/library/da2-large")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    for row in build(args.library_root, args.output):
        print(
            f"{row['name']}  seed={row['seed']}  focus={row['focus_fg']}  "
            f"contrast={row['contrast']}  share={row['share']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
