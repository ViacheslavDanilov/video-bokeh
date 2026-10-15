"""The focus rule: one object, drawn by area, and each frame's in-focus disparity."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from video_bokeh.core import _focus
from video_bokeh.core._focus import (
    choose_focus_object,
    focus_seed,
    focus_track,
    frame_focus,
    visible_masks,
)
from video_bokeh.core._seq_io import sequence_seed


def _one_hot_mask(row: int, col: int) -> np.ndarray:
    m = np.zeros((4, 4), dtype=np.float32)
    m[row, col] = 1.0
    return m


def _block(rows: slice, cols: slice) -> np.ndarray:
    m = np.zeros((4, 4), dtype=np.float32)
    m[rows, cols] = 1.0
    return m


def _two_object_frames(
    frames: list[tuple[np.ndarray | None, np.ndarray | None]],
) -> list[_focus.FrameFocus]:
    """Object 0 at disparity 0.2, object 1 at 0.8, background 0.5; None hides one."""
    measured = []
    for first, second in frames:
        empty = np.zeros((4, 4), dtype=np.float32)
        masks = [empty if first is None else first, empty if second is None else second]
        disp = np.full((4, 4), 0.5, dtype=np.float32)
        disp[masks[0] > 0.5] = 0.2
        disp[masks[1] > 0.5] = 0.8
        measured.append(frame_focus(masks, disp))
    return measured


@pytest.mark.parametrize("page", [0, 1, 2, 3, 4])
def test_an_object_counts_on_every_page(page: int) -> None:
    """An earlier reader blended pages as luminance, so only page 1 cleared the
    threshold. Every page must count the same.
    """
    masks = [np.zeros((4, 4), dtype=np.float32) for _ in range(5)]
    masks[page] = _one_hot_mask(0, 0)
    disp = np.full((4, 4), 0.8, dtype=np.float32)
    disp[0, 0] = 0.2  # only the masked pixel differs, so zf reveals the mask
    chosen, zf = focus_track([frame_focus(masks, disp)], seed=0)
    assert chosen == page
    assert zf == pytest.approx([0.2])


def test_the_fallback_is_the_mean_under_the_union_of_the_pages() -> None:
    masks = [_one_hot_mask(0, 0), _one_hot_mask(3, 3)]
    disp = np.full((4, 4), 0.9, dtype=np.float32)
    disp[0, 0] = 0.1
    disp[3, 3] = 0.3
    # Mean over both masked pixels, not over one of them and not over the frame.
    assert frame_focus(masks, disp).fallback == pytest.approx(0.2)


def test_empty_alpha_falls_back_to_the_whole_frame() -> None:
    masks = [np.zeros((4, 4), dtype=np.float32)]
    disp = np.full((4, 4), 0.6, dtype=np.float32)
    assert focus_track([frame_focus(masks, disp)], seed=0) == (
        None,
        pytest.approx([0.6]),
    )


def test_choice_is_weighted_by_area() -> None:
    picks = [choose_focus_object([3.0, 1.0], seed) for seed in range(4000)]
    assert picks.count(0) / len(picks) == pytest.approx(0.75, abs=0.03)


def test_choice_is_reproducible_and_needs_an_object() -> None:
    assert choose_focus_object([2.0, 5.0, 1.0], 7) == choose_focus_object(
        [2.0, 5.0, 1.0],
        7,
    )
    assert choose_focus_object([0.0, 0.0], 7) is None
    assert choose_focus_object([], 7) is None


def test_the_focus_is_one_object_s_disparity_in_every_frame() -> None:
    big, small = _block(slice(0, 2), slice(0, 4)), _block(slice(3, 4), slice(3, 4))
    chosen, zfs = focus_track(_two_object_frames([(big, small)] * 3), seed=0)
    # Either object, but one of them, whole: never the 0.5 background, never a mean.
    assert chosen in (0, 1)
    assert zfs == pytest.approx([{0: 0.2, 1: 0.8}[chosen]] * 3)


def test_a_hidden_object_keeps_the_focus_where_it_was() -> None:
    # Only object 1 exists, so it is the one chosen; it is hidden in frames 1 and 3.
    obj = _block(slice(0, 2), slice(0, 2))
    frames = _two_object_frames([(None, None), (None, obj), (None, None)])
    assert focus_track(frames, seed=0) == (1, pytest.approx([0.8, 0.8, 0.8]))


def test_a_sequence_without_objects_focuses_on_the_whole_frame() -> None:
    frames = _two_object_frames([(None, None)] * 2)
    assert focus_track(frames, seed=0) == (None, pytest.approx([0.5, 0.5]))


def _occluded_frame(far: np.ndarray, near: np.ndarray) -> _focus.FrameFocus:
    """Far object 0 at 0.2 under near object 1 at 0.8, composited as Stage B does: each
    mask is whole, and the disparity shows the near object wherever the two overlap.
    """
    disp = np.full((4, 4), 0.5, dtype=np.float32)
    disp[far > 0.5] = 0.2
    disp[near > 0.5] = 0.8
    return frame_focus([far, near], disp)


def test_an_occluded_object_is_focused_by_what_shows_of_it() -> None:
    far = _block(slice(0, 4), slice(0, 2))  # 8 pixels
    near = _block(slice(0, 3), slice(0, 2))  # covers 6 of them
    chosen, zf = focus_track([_occluded_frame(far, near)], seed=0)
    # Whichever is drawn, its focus is its own disparity, never a blend of the two.
    assert zf == pytest.approx([{0: 0.2, 1: 0.8}[chosen]])
    # And the far object, whichever was drawn: what shows of it is at its own 0.2.
    disp = np.where(near > 0.5, 0.8, np.where(far > 0.5, 0.2, 0.5))
    shows = visible_masks([far > 0.5, near > 0.5])[0]
    assert shows.sum() == 2
    assert disp[shows].mean() == pytest.approx(0.2)


def test_a_small_near_object_inside_a_far_mask_counts_as_hidden() -> None:
    """Every pixel of the near object lies inside the far object's mask. Its own
    disparity shows there, but nothing tells it from a far object covered: hidden is the
    safe reading, and the focus keeps its last value.
    """
    far = _block(slice(0, 4), slice(0, 4)) > 0.5
    near = _block(slice(1, 2), slice(1, 2)) > 0.5
    visible = visible_masks([far, near])
    assert not visible[1].any()
    assert visible[0].sum() == 15


def test_a_fully_covered_object_is_hidden() -> None:
    far = _block(slice(1, 3), slice(1, 3)) > 0.5
    near = _block(slice(0, 4), slice(0, 4)) > 0.5
    visible = visible_masks([far, near])
    assert not visible[0].any()
    assert visible[1].sum() == 12


def test_a_covered_frame_keeps_the_focus_whatever_its_cover_s_relief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Object 0 alone, then wholly behind object 1, whose disparity ramps 0.70 to 0.90.
    Ranked by medians, object 0 would come out in front, at the cover's 0.87.
    """
    monkeypatch.setattr(_focus, "choose_focus_object", lambda areas, seed: 0)
    # Under the cover's nearer side, where its disparity is above its own median.
    small = _block(slice(1, 3), slice(2, 4))
    big = _block(slice(0, 4), slice(0, 4))
    ramp = np.tile(np.linspace(0.70, 0.90, 4, dtype=np.float32), (4, 1))
    frames = [
        frame_focus(
            [small, np.zeros((4, 4), np.float32)], np.where(small > 0.5, 0.2, 0.5)
        ),
        frame_focus([small, big], ramp),
    ]
    assert focus_track(frames, seed=0) == (0, pytest.approx([0.2, 0.2]))


def test_the_draw_depends_on_the_sequence_s_name() -> None:
    """Seeded by name: the same sequence keeps its object, and names spread the draws."""
    big, small = _block(slice(0, 2), slice(0, 2)), _block(slice(3, 4), slice(0, 4))
    frames = _two_object_frames([(big, small)])
    names = [f"{i:04d}" for i in range(1, 21)]
    first = [focus_track(frames, focus_seed(None, name))[0] for name in names]
    again = [focus_track(frames, focus_seed(None, name))[0] for name in names]
    assert first == again
    assert len(set(first)) == 2


def test_the_draw_follows_the_scene_s_seed_where_the_dataset_records_it(
    tmp_path: Path,
) -> None:
    """The same scene focuses alike under any name, so the loader can agree with it."""
    names = [f"{i:04d}" for i in range(1, 21)]
    seeds = [7] * 10 + list(range(100, 110))
    with (tmp_path / "manifest.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["seq_id", "seed"])
        writer.writerows(zip(names, seeds, strict=True))
    for name in names:
        (tmp_path / "sequences" / name).mkdir(parents=True)
    picks = [
        choose_focus_object(
            [4.0, 4.0],
            focus_seed(sequence_seed(tmp_path / "sequences" / name), name),
        )
        for name in names
    ]
    assert len(set(picks[:10])) == 1  # one seed, one draw, whatever the name
    assert len(set(picks[10:])) == 2


def test_an_api_sequence_draws_by_the_seed_it_records(tmp_path: Path) -> None:
    picks = []
    for i, seed in enumerate((3, 3, 4, 5, 6, 7, 8, 9)):
        seq = tmp_path / f"api{i}" / "sequences" / "abc"
        seq.mkdir(parents=True)
        (seq / "sequence.json").write_text(json.dumps({"seed": seed, "n_objects": 2}))
        picks.append(
            choose_focus_object([4.0, 4.0], focus_seed(sequence_seed(seq), seq.name)),
        )
    assert picks[0] == picks[1]
    assert len(set(picks)) == 2
