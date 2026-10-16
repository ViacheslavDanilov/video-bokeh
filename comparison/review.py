#!/usr/bin/env python3
"""Lay out a compared test set for looking at, and draw its sheets from boxes kept on disk.

``collect`` reads a data root that ``run_all.sh`` has filled and writes a review folder:

    <out>/manifest.csv, <out>/scores/   the test set's manifest and every score file
    <out>/<sequence>/<method>/<frame>.png   one folder per method, the same file names in each,
                                        so that a viewer such as VPV can flip between them
    <out>/<sequence>/alpha/<frame>.tif  the alpha masks
    <out>/<sequence>/boxes.json         the candidate sheets: a frame and two boxes each
    <out>/<sequence>/sheets/<id>.png    one sheet per candidate, drawn by ``sheets``

The methods are ``all_in_focus``, ``ours``, ``drbokeh``, ``mpib``, ``bokehme`` and
``any_to_bokeh``. Each sheet is laid out as Dr.Bokeh's Fig. 1: the frames side by side, two
boxes on each, and beneath each frame the boxed regions enlarged.

The candidates are placed where Dr.Bokeh, MPIB and BokehMe part most from ours near an
object's edge: a box scores the mean absolute difference from our bokeh, over those three, in
the 16-pixel band around every edge that ``score.py`` measures. Any-to-Bokeh is left out,
since it differs everywhere. The ``--candidates`` frames whose two best boxes score most, at
least four frames apart, are kept, each with two sheets: ``a`` holds its best two boxes and
``b`` its best and third.

``sheets`` draws every candidate of ``boxes.json`` again, in the style its flags choose. A box
can be moved, or a candidate added, by editing ``boxes.json``; ``--kept`` draws only the
candidates whose sheet is still there, once the others are deleted.

    comparison/envs/render/bin/python comparison/review.py collect \\
        --data-root data/test_set --out data/test_set_review --link
    comparison/envs/render/bin/python comparison/review.py sheets data/test_set_review
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

#: Each method's folder in a review, its stream in a sequence, and its label on a sheet.
METHODS = (
    ("all_in_focus", "all_in_focus", "All-in-focus"),
    ("drbokeh", "bokeh_drbokeh", "Dr.Bokeh"),
    ("mpib", "bokeh_mpib_rt", "MPIB"),
    ("bokehme", "bokeh_bokehme", "BokehMe"),
    ("any_to_bokeh", "bokeh_any_to_bokeh", "Any-to-Bokeh"),
    ("ours", "bokeh", "Ours"),
)
#: The methods whose difference from ours places the boxes.
PLACING = ("drbokeh", "mpib", "bokehme")
SIDE = 160  # pixels a side of a box, in the frame's own pixels
GAP = 16  # pixels at least between two boxes
SPACING = 4  # frames at least between two candidate frames
BAND = 16  # pixels, as score.py's edge band

TILE = 768  # pixels a side of a frame on a sheet
PAD = 6  # pixels between tiles
LABEL = 64  # pixels of the label row
BOX_COLORS = ((59, 76, 255), (232, 66, 61))  # blue, then red
BOX_LINE = 6  # pixels, on a tile
ZOOM_LINE = 12  # pixels, on an enlarged region
EDGE = 3  # pixels of white along a colored line, when the style asks for it


def box_sums(values: np.ndarray, side: int) -> np.ndarray:
    """The sum of ``values`` over every square of ``side`` pixels, by its top-left corner."""
    total = np.pad(values.astype(np.float64), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    return (
        total[side:, side:]
        - total[:-side, side:]
        - total[side:, :-side]
        + total[:-side, :-side]
    )


def ranked_boxes(weights: np.ndarray, count: int) -> list[tuple[list[int], float]]:
    """Up to ``count`` boxes, best first, each ``GAP`` pixels clear of the ones before it.

    A box goes where the sum of ``weights`` under it is largest, then moves so that the
    weights' centroid under it is at its middle: many places hold the same sum when what
    differs is a thin band, and the middle shows both sides of the edge. A move that would
    bring it within ``GAP`` of an earlier box is not made.
    """
    score = box_sums(weights, SIDE)
    height, width = weights.shape
    boxes = []
    reach = SIDE + GAP
    for _ in range(count):
        top, left = np.unravel_index(int(np.argmax(score)), score.shape)
        if not np.isfinite(score[top, left]):
            break
        value = float(score[top, left]) / SIDE**2
        patch = weights[top : top + SIDE, left : left + SIDE]
        if patch.sum() > 0:
            ys, xs = np.indices(patch.shape)
            y = top + round(float((ys * patch).sum() / patch.sum())) - SIDE // 2
            x = left + round(float((xs * patch).sum() / patch.sum())) - SIDE // 2
            y = min(max(y, 0), height - SIDE)
            x = min(max(x, 0), width - SIDE)
            if all(max(abs(x - bx), abs(y - by)) >= reach for (bx, by, _), _ in boxes):
                top, left = y, x
        boxes.append(([int(left), int(top), SIDE], value))
        score[
            max(0, top - reach) : top + reach, max(0, left - reach) : left + reach
        ] = -np.inf
    return boxes


def _read(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.float32)


def candidates(seq: Path, frames: list[str], count: int) -> dict[str, dict]:
    """The candidate sheets of one sequence, by id."""
    from score import edge_band  # the scoring script beside this one

    from video_bokeh.core._streams import read_alpha_tiff

    streams = {name: stream for name, stream, _ in METHODS}
    per_frame = []
    for frame in frames:
        ours = _read(seq / "bokeh" / f"{frame}.png")
        difference = np.mean(
            [
                np.abs(_read(seq / streams[m] / f"{frame}.png") - ours).mean(axis=2)
                for m in PLACING
            ],
            axis=0,
        )
        band = edge_band(read_alpha_tiff(seq / "alpha" / f"{frame}.tif"), BAND)
        boxes = ranked_boxes(difference * band, 3)
        per_frame.append((sum(s for _, s in boxes[:2]), frame, boxes))
    chosen: list[tuple[float, str, list]] = []
    for item in sorted(per_frame, key=lambda x: -x[0]):
        position = frames.index(item[1])
        if all(abs(position - frames.index(c[1])) >= SPACING for c in chosen):
            chosen.append(item)
        if len(chosen) == count:
            break
    sheets = {}
    for _, frame, boxes in sorted(chosen, key=lambda c: c[1]):
        for variant, picks in (("a", (0, 1)), ("b", (0, 2))):
            if max(picks) < len(boxes):
                sheets[f"{frame}-{variant}"] = {
                    "frame": frame,
                    "boxes": [boxes[i][0] for i in picks],
                    "scores": [round(boxes[i][1], 3) for i in picks],
                    "placed": "auto",
                }
    return sheets


def _place(src: Path, dest: Path, link: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    if link:
        dest.symlink_to(src.resolve())
    else:
        shutil.copyfile(src, dest)


def collect(
    data_root: Path, out: Path, count: int, link: bool, every_frame: bool
) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))
    from video_bokeh.core._seq_io import frame_names, list_sequences

    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(data_root / "manifest.csv", out / "manifest.csv")
    for path in sorted(data_root.glob("**/comparison_*.json")):
        name = path.relative_to(data_root).as_posix().replace("/", "_")
        _place(path, out / "scores" / name, link=False)
    for seq in list_sequences(data_root, None):
        frames = [Path(n).stem for n in frame_names(seq)]
        sheets = candidates(seq, frames, count)
        kept = frames if every_frame else sorted({s["frame"] for s in sheets.values()})
        target = out / seq.name
        for frame in kept:
            for name, stream, _ in METHODS:
                _place(
                    seq / stream / f"{frame}.png", target / name / f"{frame}.png", link
                )
            _place(
                seq / "alpha" / f"{frame}.tif", target / "alpha" / f"{frame}.tif", link
            )
        (target / "boxes.json").write_text(json.dumps(sheets, indent=1) + "\n")
        print(f"  {seq.name}: {', '.join(sheets)}", flush=True)


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for name in ("Times New Roman.ttf", "times.ttf", "DejaVuSerif.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def draw_sheet(folder: Path, sheet: dict, outline: str) -> Image.Image:
    """One candidate as a sheet: the frames with their boxes, the enlargements, the labels."""
    frame, boxes = sheet["frame"], sheet["boxes"]
    zoom = (TILE - PAD) // 2
    width = len(METHODS) * TILE + (len(METHODS) - 1) * PAD
    canvas = Image.new("RGB", (width, TILE + PAD + zoom + LABEL), "white")
    font = _font(LABEL * 5 // 8)
    for c, (name, _, label) in enumerate(METHODS):
        with Image.open(folder / name / f"{frame}.png") as im:
            image = im.convert("RGB")
        scale = TILE / image.width
        tile = image.resize((TILE, TILE), Image.Resampling.LANCZOS)
        draw = ImageDraw.Draw(tile)
        x = c * (TILE + PAD)
        for k, ((left, top, side), color) in enumerate(
            zip(boxes, BOX_COLORS, strict=True)
        ):
            x0, y0, x1, y1 = (
                round(v * scale) for v in (left, top, left + side, top + side)
            )
            if outline in ("outer", "both"):
                draw.rectangle(
                    [x0 - EDGE, y0 - EDGE, x1 + EDGE, y1 + EDGE],
                    outline="white",
                    width=EDGE if outline == "outer" else BOX_LINE + 2 * EDGE,
                )
            draw.rectangle([x0, y0, x1, y1], outline=color, width=BOX_LINE)
            crop = image.crop((left, top, left + side, top + side))
            crop = crop.resize((zoom, zoom), Image.Resampling.LANCZOS)
            frame_draw = ImageDraw.Draw(crop)
            frame_draw.rectangle(
                [0, 0, zoom - 1, zoom - 1], outline=color, width=ZOOM_LINE
            )
            if outline == "both":
                inner = [
                    ZOOM_LINE,
                    ZOOM_LINE,
                    zoom - 1 - ZOOM_LINE,
                    zoom - 1 - ZOOM_LINE,
                ]
                frame_draw.rectangle(inner, outline="white", width=EDGE)
            canvas.paste(crop, (x + k * (zoom + PAD), TILE + PAD))
        canvas.paste(tile, (x, 0))
        text = ImageDraw.Draw(canvas)
        middle = (x + TILE // 2, TILE + PAD + zoom + LABEL // 2)
        text.text(middle, label, fill="black", font=font, anchor="mm")
    return canvas


def sheets(review: Path, outline: str, kept: bool, name: str) -> None:
    for boxes_file in sorted(review.glob("*/boxes.json")):
        folder = boxes_file.parent
        out = folder / name
        for sheet_id, sheet in json.loads(boxes_file.read_text()).items():
            path = out / f"{sheet_id}.png"
            if kept and not path.exists():
                continue
            out.mkdir(exist_ok=True)
            draw_sheet(folder, sheet, outline).save(path, optimize=True)
        print(f"  {folder.name}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    c = commands.add_parser("collect", help="lay out a compared data root for review")
    c.add_argument("--data-root", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument(
        "--candidates", type=int, default=3, help="candidate frames per sequence"
    )
    c.add_argument(
        "--link", action="store_true", help="link the frames instead of copying"
    )
    c.add_argument(
        "--every-frame", action="store_true", help="every frame, not the candidates'"
    )
    s = commands.add_parser("sheets", help="draw each candidate of every boxes.json")
    s.add_argument("review", type=Path)
    s.add_argument(
        "--outline",
        choices=("none", "outer", "both"),
        default="none",
        help="white along the colored lines: none, outside the boxes, or on both sides",
    )
    s.add_argument("--kept", action="store_true", help="only the sheets still on disk")
    s.add_argument(
        "--name", default="sheets", help="the folder each sequence's sheets go in"
    )
    args = parser.parse_args(argv)
    if args.command == "collect":
        collect(args.data_root, args.out, args.candidates, args.link, args.every_frame)
    else:
        sheets(args.review, args.outline, args.kept, args.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
