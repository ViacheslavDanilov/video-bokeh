"""Every asset is in the train split or the test split, by BG-20k's split or the list."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from importlib import resources
from pathlib import Path

import pytest

from video_bokeh.core._library import BACKGROUNDS, FOREGROUNDS
from video_bokeh.core._split import (
    ALL,
    TEST,
    TRAIN,
    in_split,
    listed_test_foregrounds,
    split_of,
)
from video_bokeh.library.split import page_id

PUBLISHED_SHA256 = "2215f492f3e03d6233a231a5f766ce6b2bf4ff85081736fb622c568081e1d24f"
PREDICTIONS = Path(__file__).resolve().parents[2] / "data/magick/predictions.csv"


def test_backgrounds_follow_bg20k_split() -> None:
    assert split_of(BACKGROUNDS, "testval__h_9543a95e") == TEST
    assert split_of(BACKGROUNDS, "train__h_1050b506") == TRAIN
    # A background from another pool has no BG-20k folder, so training may draw it.
    assert split_of(BACKGROUNDS, "bg_a") == TRAIN


def test_listed_foregrounds_are_test_and_others_train() -> None:
    listed = min(listed_test_foregrounds())
    assert split_of(FOREGROUNDS, listed) == TEST
    assert split_of(FOREGROUNDS, "fg_a") == TRAIN


def test_the_tracked_list_is_the_published_draw() -> None:
    # library.split drew 859 of the published library's 8,586 foregrounds. A change to
    # the file changes the fixed set, so it fails here first.
    text = resources.files("video_bokeh.core").joinpath("test_foregrounds.txt")
    data = text.read_bytes()
    assert hashlib.sha256(data).hexdigest() == PUBLISHED_SHA256
    ids = data.decode().splitlines()
    assert len(ids) == 859
    assert ids == sorted(set(ids))


def test_each_subject_is_in_the_test_split_in_its_share() -> None:
    # The counts the reference gives, from the tracked predictions.
    with PREDICTIONS.open(encoding="utf-8", newline="") as f:
        subjects = {row["page_id"]: row["top_subject"] for row in csv.DictReader(f)}
    counts = Counter(subjects[page_id(i)] for i in listed_test_foregrounds())
    assert counts == {
        "person": 397,
        "object": 233,
        "food": 141,
        "plant": 48,
        "animal": 40,
    }


def test_in_split_keeps_order_and_all_keeps_everything() -> None:
    ids = ["train__z", "testval__a", "train__b"]
    assert in_split(ids, BACKGROUNDS, TRAIN) == ["train__z", "train__b"]
    assert in_split(ids, BACKGROUNDS, TEST) == ["testval__a"]
    assert in_split(ids, BACKGROUNDS, ALL) == ids


def test_an_unknown_split_is_refused() -> None:
    with pytest.raises(ValueError, match="split must be one of train, test, all"):
        in_split(["bg_a"], BACKGROUNDS, "val")
    with pytest.raises(ValueError, match="no split for 'sequences'"):
        split_of("sequences", "0001")
