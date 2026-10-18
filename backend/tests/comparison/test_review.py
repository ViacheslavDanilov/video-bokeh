"""The review folder: one folder per method, boxes where the renderers part, sheets from them."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "comparison"))

from review import GAP, METHODS, SIDES, main, place_boxes  # noqa: E402

from video_bokeh.core._streams import write_alpha_tiff  # noqa: E402

SIZE = 512
FRAMES = [f"{i:02d}" for i in range(1, 11)]
EDGE_AT = 300  # the object's left edge, in pixels
DIFFERS_AT = 6  # the frame where the published renderers part from ours
DIFFERS_AT_NAME = f"{DIFFERS_AT:02d}"


def _write(path: Path, rgb: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb.astype(np.uint8)).save(path)


def _data_root(root: Path) -> Path:
    """One sequence whose object's edge runs down x = EDGE_AT. The placing renderers differ
    from ours a little all along it, and at one frame much more across its top."""
    seq = root / "sequences" / "any-01"
    alpha = np.zeros((SIZE, SIZE), np.float32)
    alpha[:, EDGE_AT:] = 1.0
    base = np.full((SIZE, SIZE, 3), 100, np.uint8)
    (seq / "alpha").mkdir(parents=True)
    for frame in FRAMES:
        write_alpha_tiff(seq / "alpha" / f"{frame}.tif", [alpha])
        for _, stream, _ in METHODS:
            image = base.copy()
            if stream not in ("bokeh", "all_in_focus"):
                image[:, EDGE_AT - 40 : EDGE_AT + 40] = (
                    110  # they part a little all along
                )
                if frame == DIFFERS_AT_NAME:
                    image[20:100, EDGE_AT - 40 : EDGE_AT + 40] = 200
            _write(seq / stream / f"{frame}.png", image)
    with (root / "manifest.csv").open("w", newline="") as f:
        csv.writer(f).writerows([["seq_id", "seed"], ["any-01", "0"]])
    (root / "comparison_drbokeh.json").write_text("{}")
    return root


def test_collect_lays_out_methods_and_places_boxes_where_they_part(
    tmp_path: Path,
) -> None:
    out = tmp_path / "review"
    data = _data_root(tmp_path / "data")
    main(["collect", "--data-root", str(data), "--out", str(out), "--candidates", "2"])

    seq = out / "any-01"
    sheets = json.loads((seq / "boxes.json").read_text())
    frames = {s["frame"] for s in sheets.values()}
    assert DIFFERS_AT_NAME in frames and len(frames) == 2
    best = sheets[f"{DIFFERS_AT_NAME}-a"]
    left, top, side = best["boxes"][0]
    assert side in SIDES
    assert left < EDGE_AT < left + side  # on the edge where they part
    assert top < 100
    for name, _, _ in METHODS:
        assert sorted(p.stem for p in (seq / name).glob("*.png")) == sorted(frames)
    assert (out / "manifest.csv").is_file()
    assert (out / "scores" / "comparison_drbokeh.json").is_file()


def _clear(a: list[int], b: list[int]) -> bool:
    (al, at, aside), (bl, bt, bside) = a, b
    return (
        al + aside + GAP <= bl
        or bl + bside + GAP <= al
        or at + aside + GAP <= bt
        or bt + bside + GAP <= at
    )


def test_boxes_stay_clear_of_each_other() -> None:
    alpha = np.zeros((SIZE, SIZE))
    alpha[:, EDGE_AT:] = 1.0
    difference = np.ones((SIZE, SIZE))
    boxes = [box for box, _ in place_boxes(alpha, difference, np.zeros_like(alpha), 3)]
    assert len(boxes) >= 2
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            assert _clear(a, b)


def test_a_box_holds_a_tip_whole_rather_than_cut_through_it() -> None:
    alpha = np.zeros((SIZE, SIZE))
    alpha[300:, 240:272] = 1.0  # a thin upright object, its tip at y = 300
    difference = np.ones((SIZE, SIZE))
    (left, top, side), _ = place_boxes(alpha, difference, np.zeros_like(alpha), 1)[0]
    assert top < 300 < top + side  # the tip and what lies above it
    assert left <= 240 and 272 <= left + side  # all of its width


def test_sheets_are_drawn_from_the_boxes_and_kept_ones_redrawn(tmp_path: Path) -> None:
    out = tmp_path / "review"
    data = _data_root(tmp_path / "data")
    main(["collect", "--data-root", str(data), "--out", str(out), "--candidates", "2"])
    main(["sheets", str(out)])
    drawn = sorted((out / "any-01" / "sheets").glob("*.png"))
    sheets = json.loads((out / "any-01" / "boxes.json").read_text())
    assert [p.stem for p in drawn] == sorted(sheets)

    keep = drawn[0]
    for path in drawn[1:]:
        path.unlink()
    main(["sheets", str(out), "--kept", "--outline", "both"])
    assert sorted((out / "any-01" / "sheets").glob("*.png")) == [keep]
    main(["sheets", str(out), "--kept", "--outline", "outer", "--name", "trial"])
    assert [p.name for p in (out / "any-01" / "trial").glob("*.png")] == [keep.name]


def test_boxes_go_on_the_object_in_focus(tmp_path: Path) -> None:
    data = tmp_path / "data"
    seq = data / "sequences" / "any-01"
    (seq / "alpha").mkdir(parents=True)
    (seq / "bokeh").mkdir(parents=True)
    (seq / "bokeh" / "focus.json").write_text(json.dumps({"object": 1}))
    left_object = np.zeros((SIZE, SIZE), np.float32)
    left_object[:, :150] = 1.0
    right_object = np.zeros((SIZE, SIZE), np.float32)
    right_object[:, 370:] = 1.0
    base = np.full((SIZE, SIZE, 3), 100, np.uint8)
    for frame in FRAMES[:2]:
        write_alpha_tiff(seq / "alpha" / f"{frame}.tif", [left_object, right_object])
        for _, stream, _ in METHODS:
            image = base.copy()
            if stream not in ("bokeh", "all_in_focus"):
                image[:, 130:170] = 250  # they part most at the blurred object's edge
                image[:, 350:390] = 160
            _write(seq / stream / f"{frame}.png", image)
    with (data / "manifest.csv").open("w", newline="") as f:
        csv.writer(f).writerows([["seq_id", "seed"], ["any-01", "0"]])
    out = tmp_path / "review"
    main(["collect", "--data-root", str(data), "--out", str(out), "--candidates", "1"])
    sheets = json.loads((out / "any-01" / "boxes.json").read_text())
    for sheet in sheets.values():
        for left, _, side in sheet["boxes"]:
            assert left < 370 < left + side  # the edge of object 1, the one in focus


def test_boxes_skip_the_focus_edge_a_nearer_object_hides(tmp_path: Path) -> None:
    data = tmp_path / "data"
    seq = data / "sequences" / "any-01"
    (seq / "bokeh").mkdir(parents=True)
    (seq / "bokeh" / "focus.json").write_text(json.dumps({"object": 0}))
    (seq / "alpha").mkdir()
    (seq / "layers").mkdir()
    (seq / "layers" / "paint_order.json").write_text(json.dumps([[0, 1]] * 2))
    focused = np.zeros((SIZE, SIZE), np.float32)
    focused[:, 200:] = 1.0
    nearer = np.zeros((SIZE, SIZE), np.float32)
    nearer[:256, 100:450] = 1.0  # hides the focused object's edge above y = 256
    base = np.full((SIZE, SIZE, 3), 100, np.uint8)
    for frame in FRAMES[:2]:
        write_alpha_tiff(seq / "alpha" / f"{frame}.tif", [focused, nearer])
        for _, stream, _ in METHODS:
            image = base.copy()
            if stream not in ("bokeh", "all_in_focus"):
                image[:, 180:220] = 120
                image[:256, 180:220] = 250  # they part most where the edge is hidden
                image[:256, 430:470] = 140
            _write(seq / stream / f"{frame}.png", image)
    with (data / "manifest.csv").open("w", newline="") as f:
        csv.writer(f).writerows([["seq_id", "seed"], ["any-01", "0"]])
    out = tmp_path / "review"
    main(["collect", "--data-root", str(data), "--out", str(out), "--candidates", "1"])
    sheets = json.loads((out / "any-01" / "boxes.json").read_text())
    assert sheets
    for sheet in sheets.values():
        for left, top, side in sheet["boxes"]:
            hidden = left < 200 < left + side and top + side <= 256
            assert not hidden  # a box on the hidden edge would show the nearer object


def test_every_frame_can_be_linked(tmp_path: Path) -> None:
    out = tmp_path / "review"
    data = _data_root(tmp_path / "data")
    main(
        [
            "collect",
            "--data-root",
            str(data),
            "--out",
            str(out),
            "--link",
            "--every-frame",
        ]
    )
    ours = sorted((out / "any-01" / "ours").iterdir())
    assert [p.stem for p in ours] == FRAMES
    assert all(p.is_symlink() for p in ours)
