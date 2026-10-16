"""The review folder: one folder per method, boxes where the renderers part, sheets from them."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "comparison"))

from review import GAP, METHODS, SIDE, main, ranked_boxes  # noqa: E402

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
    """One sequence whose object's edge runs down x = EDGE_AT; at one frame, every placing
    renderer differs from ours in a square across the top of that edge."""
    seq = root / "sequences" / "any-01"
    alpha = np.zeros((SIZE, SIZE), np.float32)
    alpha[:, EDGE_AT:] = 1.0
    base = np.full((SIZE, SIZE, 3), 100, np.uint8)
    (seq / "alpha").mkdir(parents=True)
    for frame in FRAMES:
        write_alpha_tiff(seq / "alpha" / f"{frame}.tif", [alpha])
        for _, stream, _ in METHODS:
            image = base.copy()
            if frame == DIFFERS_AT_NAME and stream not in ("bokeh", "all_in_focus"):
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
    assert side == SIDE
    assert abs(left + side // 2 - EDGE_AT) <= 2  # centered on the edge where they part
    assert top <= 20 and 100 <= top + side
    for name, _, _ in METHODS:
        assert sorted(p.stem for p in (seq / name).glob("*.png")) == sorted(frames)
    assert (out / "manifest.csv").is_file()
    assert (out / "scores" / "comparison_drbokeh.json").is_file()


def test_centered_boxes_stay_clear_of_each_other() -> None:
    weights = np.zeros((SIZE, SIZE))
    weights[200:240, 100:260] = 1.0  # the first box takes this run of the band
    weights[200:240, 260:282] = 0.5  # a second box, centered on this tail, covers it
    boxes = [box for box, _ in ranked_boxes(weights, 3)]
    for i, (a_left, a_top, side) in enumerate(boxes):
        for b_left, b_top, _ in boxes[i + 1 :]:
            assert max(abs(a_left - b_left), abs(a_top - b_top)) >= side + GAP


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
