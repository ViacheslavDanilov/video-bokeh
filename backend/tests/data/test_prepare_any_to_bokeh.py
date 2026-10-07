from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from video_bokeh.bridge.any_to_bokeh import (
    SequenceInputs,
    choose_focus_object,
    main,
    visible_masks,
    write_inputs,
)
from video_bokeh.core._streams import write_alpha_tiff, write_disparity_png


def _write_rgb(path: Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.full((4, 4, 3), value, dtype=np.uint8)
    Image.fromarray(arr, mode="RGB").save(path)


def _write_alpha(path: Path, masks: list[np.ndarray] | None = None) -> None:
    """Write the alpha stream. One quadrant occupied, unless masks are given."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if masks is None:
        m = np.zeros((4, 4), dtype=np.float32)
        m[:2, :2] = 1.0
        masks = [m]
    write_alpha_tiff(path.with_suffix(".tif"), masks)


def _one_hot_mask(row: int, col: int) -> np.ndarray:
    m = np.zeros((4, 4), dtype=np.float32)
    m[row, col] = 1.0
    return m


def _write_disparity(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_disparity_png(path.with_suffix(".png"), arr.astype(np.float32))


def test_prepare_any_to_bokeh_writes_one_based_frames_and_csv(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "synth"
    seq_dir = data_root / "sequences" / "0001"
    _write_rgb(seq_dir / "all_in_focus" / "01.png", 10)
    _write_rgb(seq_dir / "all_in_focus" / "02.png", 20)
    _write_alpha(seq_dir / "alpha" / "01.tif")
    _write_alpha(seq_dir / "alpha" / "02.tif")
    _write_disparity(
        seq_dir / "disparity" / "01",
        np.array(
            [
                [0.25, 0.25, 0.75, 0.75],
                [0.25, 0.25, 0.75, 0.75],
                [0.75, 0.75, 0.75, 0.75],
                [0.75, 0.75, 0.75, 0.75],
            ],
            dtype=np.float32,
        ),
    )
    _write_disparity(
        seq_dir / "disparity" / "02",
        np.full((4, 4), 0.5, dtype=np.float32),
    )

    a2b_root = tmp_path / "any-to-bokeh"
    rc = main(
        [
            "--data-root",
            str(data_root),
            "--a2b-root",
            str(a2b_root),
            "--dataset-name",
            "fixture",
            "--seqs",
            "0001",
        ],
    )

    assert rc == 0
    video_dir = a2b_root / "demo_dataset" / "fixture" / "videos" / "0001"
    disp_dir = a2b_root / "demo_dataset" / "fixture" / "disp" / "0001"
    assert sorted(path.name for path in video_dir.glob("*.png")) == ["01.png", "02.png"]
    disp_names = sorted(path.name for path in disp_dir.glob("*.png"))
    assert len(disp_names) == 2
    assert disp_names[0].startswith("01_zf_")
    assert disp_names[1].startswith("02_zf_")
    assert not any(name.startswith("00_zf_") for name in disp_names)

    disp_img = Image.open(disp_dir / disp_names[0])
    assert disp_img.mode == "L"
    assert disp_names[0] == "01_zf_0.250980.png"

    with (a2b_root / "csv_file" / "fixture.csv").open(
        newline="",
        encoding="utf-8",
    ) as f:
        rows = list(csv.DictReader(f))
    assert rows == [
        {
            "aif_folder": "demo_dataset/fixture/videos/0001",
            "disp_folder": "demo_dataset/fixture/disp/0001",
            "k": "16",
        },
    ]


def test_fixed_focus_is_preserved_across_frames(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    seq = root / "sequences" / "0001"
    for index, depth in enumerate((0.2, 0.8), start=1):
        _write_rgb(seq / "all_in_focus" / f"{index:02}.png", 100)
        _write_disparity(
            seq / "disparity" / f"{index:02}",
            np.full((4, 4), depth, dtype=np.float32),
        )
    target = tmp_path / "a2b"
    assert (
        main(
            [
                "--data-root",
                str(root),
                "--a2b-root",
                str(target),
                "--focus-disparity",
                "0.5",
            ],
        )
        == 0
    )
    assert sorted(
        p.name for p in (target / "demo_dataset/dataset/disp/0001").glob("*.png")
    ) == [
        "01_zf_0.500000.png",
        "02_zf_0.500000.png",
    ]


@pytest.mark.parametrize("focus", ["-0.1", "1.1", "nan"])
def test_invalid_fixed_focus_writes_nothing(tmp_path: Path, focus: str) -> None:
    target = tmp_path / "a2b"
    with pytest.raises(SystemExit):
        main(
            [
                "--data-root",
                str(tmp_path),
                "--a2b-root",
                str(target),
                "--focus-disparity",
                focus,
            ],
        )
    assert not target.exists()


def _seq_with_alpha(tmp_path: Path, masks: list[np.ndarray], disp: np.ndarray) -> Path:
    seq = tmp_path / "data" / "sequences" / "0001"
    _write_rgb(seq / "all_in_focus" / "01.png", 100)
    _write_alpha(seq / "alpha" / "01.tif", masks)
    _write_disparity(seq / "disparity" / "01.png", disp)
    return tmp_path / "data"


def _zf_of(target: Path) -> float:
    name = next((target / "demo_dataset/data/disp/0001").glob("*.png")).name
    return float(name.split("_zf_")[1].removesuffix(".png"))


@pytest.mark.parametrize("page", [0, 1, 2, 3, 4])
def test_focus_mask_sees_an_object_on_every_page(tmp_path: Path, page: int) -> None:
    """The old reader blended pages as luminance, so only page 1 cleared the threshold.

    An object alone on page 0 scored 0.299 * 255 = 76 and one on page 2 scored 29, both
    under the 127 cut, so `--focus alpha` silently fell back to whole-frame focus. Every
    page must count the same.
    """
    masks = [np.zeros((4, 4), dtype=np.float32) for _ in range(5)]
    masks[page] = _one_hot_mask(0, 0)
    disp = np.full((4, 4), 0.8, dtype=np.float32)
    disp[0, 0] = 0.2  # only the masked pixel differs, so zf reveals the mask

    root = _seq_with_alpha(tmp_path, masks, disp)
    target = tmp_path / "a2b"
    assert main(["--data-root", str(root), "--a2b-root", str(target)]) == 0

    # Focus must come from the masked pixel alone, not from the whole frame.
    assert _zf_of(target) == pytest.approx(0.2, abs=2e-3)


def test_focus_mask_is_the_union_of_the_pages(tmp_path: Path) -> None:
    masks = [_one_hot_mask(0, 0), _one_hot_mask(3, 3)]
    disp = np.full((4, 4), 0.9, dtype=np.float32)
    disp[0, 0] = 0.1
    disp[3, 3] = 0.3

    root = _seq_with_alpha(tmp_path, masks, disp)
    target = tmp_path / "a2b"
    args = ["--data-root", str(root), "--a2b-root", str(target), "--focus", "alpha"]
    assert main(args) == 0

    # Mean over both masked pixels, not over one of them and not over the frame.
    assert _zf_of(target) == pytest.approx(0.2, abs=2e-3)


def test_empty_alpha_falls_back_to_whole_frame_focus(tmp_path: Path) -> None:
    masks = [np.zeros((4, 4), dtype=np.float32)]
    disp = np.full((4, 4), 0.6, dtype=np.float32)

    root = _seq_with_alpha(tmp_path, masks, disp)
    target = tmp_path / "a2b"
    assert main(["--data-root", str(root), "--a2b-root", str(target)]) == 0
    assert _zf_of(target) == pytest.approx(0.6, abs=2e-3)


def test_16_bit_disparity_is_quantized_once(tmp_path: Path) -> None:
    """Reading 16-bit and re-quantizing twice would round differently than once.

    Values are picked to sit just under an 8-bit boundary, where a second rounding
    of an already-rounded value shows up.
    """
    disp = np.array(
        [[0.5 - 0.6 / 255, 0.5 + 0.6 / 255], [0.25, 0.75]],
        dtype=np.float32,
    )
    seq = tmp_path / "data" / "sequences" / "0001"
    _write_rgb(seq / "all_in_focus" / "01.png", 100)
    _write_alpha(seq / "alpha" / "01.tif", [np.ones((2, 2), dtype=np.float32)])
    _write_disparity(seq / "disparity" / "01.png", disp)

    target = tmp_path / "a2b"
    assert main(["--data-root", str(tmp_path / "data"), "--a2b-root", str(target)]) == 0

    written = np.asarray(
        Image.open(next((target / "demo_dataset/data/disp/0001").glob("*.png"))),
    )
    expected = (disp * 255.0).round().astype(np.uint8)
    assert np.array_equal(written, expected)


def test_alpha_directory_without_tif_frames_is_an_error(tmp_path: Path) -> None:
    """The old alpha/*.png layout must fail loudly, not fall back to whole-frame focus.

    An empty .tif listing short-circuited the frame-count guard, so `_load_focus_mask`
    received None and returned an all-ones mask -- the same silent fallback the union
    fix removed, re-entering through a different door.
    """
    seq = tmp_path / "data" / "sequences" / "0001"
    _write_rgb(seq / "all_in_focus" / "01.png", 100)
    (seq / "alpha").mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.zeros((4, 4, 3), np.uint8), "RGB").save(seq / "alpha" / "01.png")
    _write_disparity(
        seq / "disparity" / "01.png",
        np.full((4, 4), 0.9, dtype=np.float32),
    )

    with pytest.raises(ValueError, match="no .tif frames"):
        main(
            [
                "--data-root",
                str(tmp_path / "data"),
                "--a2b-root",
                str(tmp_path / "a2b"),
            ],
        )


# --focus object, the default: one object, chosen by area, holds the focus.


def _zfs_of(target: Path, seq: str = "0001", dataset: str = "data") -> list[float]:
    names = sorted((target / f"demo_dataset/{dataset}/disp/{seq}").glob("*.png"))
    return [float(p.name.split("_zf_")[1].removesuffix(".png")) for p in names]


def _two_object_sequence(
    root: Path,
    seq: str,
    frames: list[tuple[np.ndarray | None, np.ndarray | None]],
) -> None:
    """Object 0 at disparity 0.2, object 1 at 0.8, background 0.5; None hides one."""
    for t, (first, second) in enumerate(frames, start=1):
        stem = f"{t:02d}"
        empty = np.zeros((4, 4), dtype=np.float32)
        masks = [empty if first is None else first, empty if second is None else second]
        disp = np.full((4, 4), 0.5, dtype=np.float32)
        disp[masks[0] > 0.5] = 0.2
        disp[masks[1] > 0.5] = 0.8
        _write_rgb(root / "sequences" / seq / "all_in_focus" / f"{stem}.png", 100)
        _write_alpha(root / "sequences" / seq / "alpha" / f"{stem}.tif", masks)
        _write_disparity(root / "sequences" / seq / "disparity" / f"{stem}.png", disp)


def _block(rows: slice, cols: slice) -> np.ndarray:
    m = np.zeros((4, 4), dtype=np.float32)
    m[rows, cols] = 1.0
    return m


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


def test_the_focus_is_one_object_s_disparity_in_every_frame(tmp_path: Path) -> None:
    root = tmp_path / "data"
    big, small = _block(slice(0, 2), slice(0, 4)), _block(slice(3, 4), slice(3, 4))
    _two_object_sequence(root, "0001", [(big, small)] * 3)
    target = tmp_path / "a2b"
    assert main(["--data-root", str(root), "--a2b-root", str(target)]) == 0
    zfs = _zfs_of(target)
    # Either object, but one of them, whole: never the 0.5 background, never a mean.
    assert len(set(zfs)) == 1
    assert zfs[0] == pytest.approx(0.2, abs=3e-3) or zfs[0] == pytest.approx(
        0.8,
        abs=3e-3,
    )


def test_a_hidden_object_keeps_the_focus_where_it_was(tmp_path: Path) -> None:
    root = tmp_path / "data"
    # Only object 1 exists, so it is the one chosen; it is hidden in frames 1 and 3.
    obj = _block(slice(0, 2), slice(0, 2))
    _two_object_sequence(root, "0001", [(None, None), (None, obj), (None, None)])
    target = tmp_path / "a2b"
    assert main(["--data-root", str(root), "--a2b-root", str(target)]) == 0
    assert _zfs_of(target) == pytest.approx([0.8, 0.8, 0.8], abs=3e-3)


def test_a_sequence_without_objects_focuses_on_the_whole_frame(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _two_object_sequence(root, "0001", [(None, None)] * 2)
    target = tmp_path / "a2b"
    assert main(["--data-root", str(root), "--a2b-root", str(target)]) == 0
    assert _zfs_of(target) == pytest.approx([0.5, 0.5], abs=3e-3)


def test_write_inputs_reports_the_chosen_object(tmp_path: Path) -> None:
    root = tmp_path / "data"
    obj = _block(slice(0, 2), slice(0, 2))
    _two_object_sequence(root, "0001", [(None, obj)] * 2)
    (written,) = write_inputs(
        [root / "sequences" / "0001"],
        videos_root=tmp_path / "v",
        disp_root=tmp_path / "d",
        csv_path=tmp_path / "in.csv",
        k="16",
        focus="object",
    )
    assert written.frames == 2
    assert written.focus_object == 1
    assert written.zf == pytest.approx([0.8, 0.8], abs=3e-3)


def _occluded_sequence(root: Path, seq: str, far: np.ndarray, near: np.ndarray) -> None:
    """Far object 0 at 0.2 under near object 1 at 0.8, composited as Stage B does: each
    mask is whole, and the disparity shows the near object wherever the two overlap.
    """
    disp = np.full((4, 4), 0.5, dtype=np.float32)
    disp[far > 0.5] = 0.2
    disp[near > 0.5] = 0.8
    _write_rgb(root / "sequences" / seq / "all_in_focus" / "01.png", 100)
    _write_alpha(root / "sequences" / seq / "alpha" / "01.tif", [far, near])
    _write_disparity(root / "sequences" / seq / "disparity" / "01.png", disp)


def _focus_of(tmp_path: Path, far: np.ndarray, near: np.ndarray) -> SequenceInputs:
    root = tmp_path / "data"
    _occluded_sequence(root, "0001", far, near)
    (written,) = write_inputs(
        [root / "sequences" / "0001"],
        videos_root=tmp_path / "v",
        disp_root=tmp_path / "d",
        csv_path=tmp_path / "in.csv",
        k="16",
    )
    return written


def test_an_occluded_object_is_focused_by_what_shows_of_it(tmp_path: Path) -> None:
    far = _block(slice(0, 4), slice(0, 2))  # 8 pixels
    near = _block(slice(0, 3), slice(0, 2))  # covers 6 of them
    written = _focus_of(tmp_path, far, near)
    # Whichever is drawn, its focus is its own disparity, never a blend of the two.
    expected = {0: 0.2, 1: 0.8}[written.focus_object]
    assert written.zf == pytest.approx([expected], abs=3e-3)
    # And the far object, whichever was drawn: what shows of it is at its own 0.2.
    disp = np.where(near > 0.5, 0.8, np.where(far > 0.5, 0.2, 0.5))
    shows = visible_masks([far > 0.5, near > 0.5], disp)[0]
    assert shows.sum() == 2
    assert disp[shows].mean() == pytest.approx(0.2)


def test_a_small_near_object_over_a_far_one_is_seen(tmp_path: Path) -> None:
    """Every pixel of the near object lies inside the far object's mask."""
    far = _block(slice(0, 4), slice(0, 4))
    near = _block(slice(1, 2), slice(1, 2))
    visible = visible_masks(
        [far > 0.5, near > 0.5],
        np.where(near > 0.5, 0.8, 0.2).astype(np.float32),
    )
    assert visible[1].sum() == 1
    assert visible[0].sum() == 15


def test_a_fully_covered_object_is_hidden() -> None:
    far = _block(slice(0, 2), slice(0, 2)) > 0.5
    near = _block(slice(0, 4), slice(0, 4)) > 0.5
    disp = np.where(near, 0.8, 0.2).astype(np.float32)
    visible = visible_masks([far, near], disp)
    assert not visible[0].any()
    assert visible[1].sum() == 16


def test_the_draw_depends_on_the_sequence_s_name(tmp_path: Path) -> None:
    """Seeded by name: the same sequence keeps its object, and names spread the draws."""
    root = tmp_path / "data"
    big, small = _block(slice(0, 2), slice(0, 2)), _block(slice(3, 4), slice(0, 4))
    names = [f"{i:04d}" for i in range(1, 21)]
    for name in names:
        _two_object_sequence(root, name, [(big, small)])
    seqs = [root / "sequences" / n for n in names]
    first = write_inputs(seqs, tmp_path / "v", tmp_path / "d", tmp_path / "a.csv", "16")
    again = write_inputs(
        seqs, tmp_path / "v2", tmp_path / "d2", tmp_path / "b.csv", "16"
    )
    assert [w.focus_object for w in first] == [w.focus_object for w in again]
    assert len({w.focus_object for w in first}) == 2


def test_a_pinned_focus_does_not_read_the_alpha(tmp_path: Path) -> None:
    root = tmp_path / "data"
    obj = _block(slice(0, 2), slice(0, 2))
    _two_object_sequence(root, "0001", [(obj, None)] * 2)
    (root / "sequences" / "0001" / "alpha" / "02.tif").unlink()
    (written,) = write_inputs(
        [root / "sequences" / "0001"],
        tmp_path / "v",
        tmp_path / "d",
        tmp_path / "in.csv",
        "16",
        focus_disparity=0.4,
    )
    assert written.zf == [0.4, 0.4]


def test_an_unknown_focus_mode_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="focus"):
        write_inputs(
            [], tmp_path / "v", tmp_path / "d", tmp_path / "in.csv", "16", focus="obj"
        )
