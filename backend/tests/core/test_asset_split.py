"""Every asset is in the train split or the test split, by BG-20k's split or the list."""

from __future__ import annotations

from importlib import resources

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
    # the file changes the benchmark, so it fails here first.
    text = resources.files("video_bokeh.core").joinpath("test_foregrounds.txt")
    ids = text.read_text().splitlines()
    assert len(ids) == 859
    assert ids == sorted(set(ids))


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
