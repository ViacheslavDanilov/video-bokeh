"""Which assets training draws from and which only the benchmark draws from.

Every asset of a library is in one of two splits, ``train`` and ``test``. Sequences made
from test assets show a network objects and backgrounds it never trained on.

- **Backgrounds follow BG-20k's own split.** An id that starts with ``testval__`` came
  from BG-20k's testval folder and is a test asset; every other background is a train
  asset.
- **Foregrounds are listed.** MAGICK has no split of its own, so the test foregrounds are
  the ids in ``test_foregrounds.txt`` beside this file, drawn once by
  ``video_bokeh.library.split`` and never drawn again. Every other foreground is a train
  asset, so a library of other assets is all train.

``all`` takes both splits.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import cache
from importlib import resources

from video_bokeh.core._library import BACKGROUNDS, FOREGROUNDS

TRAIN = "train"
TEST = "test"
ALL = "all"
SPLITS = (TRAIN, TEST, ALL)
#: The prefix BG-20k's testval backgrounds carry in an asset pool.
TEST_BACKGROUND_PREFIX = "testval__"
#: The file that lists the test foregrounds, one id per line, beside this module.
TEST_FOREGROUNDS = "test_foregrounds.txt"


@cache
def listed_test_foregrounds() -> frozenset[str]:
    """The ids of the foregrounds in the test split."""
    text = (
        resources.files("video_bokeh.core")
        .joinpath(TEST_FOREGROUNDS)
        .read_text(encoding="utf-8")
    )
    return frozenset(line for line in text.splitlines() if line)


def split_of(kind: str, asset_id: str) -> str:
    """The split an asset of ``kind``, ``foregrounds`` or ``backgrounds``, is in."""
    if kind == BACKGROUNDS:
        return TEST if asset_id.startswith(TEST_BACKGROUND_PREFIX) else TRAIN
    if kind == FOREGROUNDS:
        return TEST if asset_id in listed_test_foregrounds() else TRAIN
    raise ValueError(f"no split for {kind!r}: assets are foregrounds or backgrounds")


def in_split(ids: Iterable[str], kind: str, split: str) -> list[str]:
    """The ids of ``ids`` in ``split``, in their order."""
    if split not in SPLITS:
        raise ValueError(f"split must be one of {', '.join(SPLITS)}, not {split!r}")
    if split == ALL:
        return list(ids)
    return [i for i in ids if split_of(kind, i) == split]
