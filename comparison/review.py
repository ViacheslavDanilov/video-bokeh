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
``any_to_bokeh``. ``mpib`` is MPIB's ray tracer composited in gamma values, the stream
``bokeh_mpib_rt_cg``, or ``bokeh_mpib_rt``, the linear one, in a sequence that has no gamma one.
Each sheet is laid out as Dr.Bokeh's Fig. 1: the frames side by side, two
boxes on each, and beneath each frame the boxed regions enlarged.

The boxes go on the edge of the object in focus, the one ``bokeh/focus.json`` names, where
no nearer object hides it, or on the edge of any object when the focus is on the background.
The outline a nearer object draws across the focused one is not that object's edge: what
shows there is the nearer object's blur, so the edge within 16 pixels of it does not count,
and no box is more than a twentieth filled by a nearer object.
A box is a square of 96, 128, 176 or 240 pixels: every enlargement is drawn the same size, so
a smaller box is a closer look. A box scores the product of four things:

- how much Dr.Bokeh, MPIB and BokehMe differ from our bokeh, on average, in the 16-pixel band
  around the object's edge that ``score.py`` measures. Any-to-Bokeh is left out, since it
  differs everywhere;
- how blurred the rest of the box is, against the all-in-focus frame, so that the bokeh behind
  the sharp edge shows;
- how much of the box the object fills, best at about two fifths, so that both sides of the
  edge show;
- whether the object crosses the box from one side to the opposite one. A box that holds a
  tip, such as a flame or the top of a head, whole scores almost three times as much as one
  that cuts through it.

A larger box, which shows more of what lies around the edge, is slightly preferred.

The ``--candidates`` frames whose two best boxes score most, at least four frames apart, are
kept, each with two sheets: ``a`` holds its best two boxes and ``b`` its best and third.

``sheets`` draws every candidate of ``boxes.json`` again, in the style its flags choose. A box
can be moved, or a candidate added, by editing ``boxes.json``; ``--kept`` draws only the
candidates whose sheet is still in ``sheets/``, once the others are deleted, into ``sheets/``
or, with ``--name``, into a folder for a trial style.

    comparison/envs/render/bin/python comparison/review.py collect \\
        --data-root data/test_set --out data/test_set_review --link
    comparison/envs/render/bin/python comparison/review.py sheets data/test_set_review
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

#: Each method's folder in a review, its stream in a sequence, and its label on a sheet.
#: MPIB is its ray tracer composited in gamma values, the comparison's reference.
METHODS = (
    ("all_in_focus", "all_in_focus", "All-in-focus"),
    ("drbokeh", "bokeh_drbokeh", "Dr.Bokeh"),
    ("mpib", "bokeh_mpib_rt_cg", "MPIB"),
    ("bokehme", "bokeh_bokehme", "BokehMe"),
    ("any_to_bokeh", "bokeh_any_to_bokeh", "Any-to-Bokeh"),
    ("ours", "bokeh", "Ours"),
)
#: The stream MPIB's folder reads in a sequence that has no gamma-composited one, as the
#: data roots rendered before ``run_mpib_rt.py --composite gamma`` do.
MPIB_LINEAR = "bokeh_mpib_rt"
#: The methods whose difference from ours places the boxes.
PLACING = ("drbokeh", "mpib", "bokehme")
SIDES = (96, 128, 176, 240)  # pixels a side of a box, in the frame's own pixels
STRIDE = 8  # pixels between the boxes tried
GAP = 16  # pixels at least between two boxes
SPACING = 4  # frames at least between two candidate frames
BAND = 16  # pixels, as score.py's edge band
BOKEH_FULL = (
    12.0  # gray levels of blur at which the rest of a box counts as fully defocused
)
FILL_BEST = 0.4  # the share of a box the object fills at best
CROSSED = (
    0.35  # the factor of a box that the object crosses from one side to the opposite
)
NEARER_MAX = 0.05  # the share of a box a nearer object may fill at most
SIZE_POWER = (
    0.3  # how much a larger box, which shows more around the edge, is preferred
)

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


def _edge_sums(mask: np.ndarray, side: int) -> tuple[np.ndarray, ...]:
    """How much of ``mask`` lies on each side of every box: top, bottom, left, right."""
    rows = np.pad(mask.astype(np.float64), ((0, 0), (1, 0))).cumsum(1)
    across = rows[:, side:] - rows[:, :-side]
    cols = np.pad(mask.astype(np.float64), ((1, 0), (0, 0))).cumsum(0)
    down = cols[side:, :] - cols[:-side, :]
    return (
        across[: -side + 1],
        across[side - 1 :],
        down[:, : -side + 1],
        down[:, side - 1 :],
    )


def box_scores(
    alpha: np.ndarray,
    band: np.ndarray,
    difference: np.ndarray,
    blur: np.ndarray,
    side: int,
) -> np.ndarray:
    """The score of every box of ``side`` pixels, by its top-left corner; 0 where it fails."""
    area = float(side * side)
    in_band = box_sums(band, side)
    differs = box_sums(difference * band, side) / np.maximum(in_band, 1.0)
    behind = 1.0 - alpha
    defocus = box_sums(blur * behind, side) / np.maximum(box_sums(behind, side), 1.0)
    shown = 0.25 + 0.75 * np.minimum(defocus / BOKEH_FULL, 1.0)
    fill = box_sums(alpha, side) / area
    filled = np.clip(1.0 - np.abs(fill - FILL_BEST) / 0.35, 0.0, 1.0)
    top, bottom, left, right = (e / side > 0.03 for e in _edge_sums(alpha > 0.5, side))
    crossed = (top & bottom) | (left & right)
    whole = np.where(crossed, CROSSED, 1.0)
    context = (side / SIDES[-2]) ** SIZE_POWER
    score = differs * shown * filled * whole * context
    return np.where(in_band >= 0.04 * area, score, 0.0)


def _clear(box: list[int], others: list[list[int]]) -> bool:
    """Whether ``box`` stays ``GAP`` pixels clear of every box in ``others``."""
    left, top, side = box
    return all(
        left + side + GAP <= o_left
        or o_left + o_side + GAP <= left
        or top + side + GAP <= o_top
        or o_top + o_side + GAP <= top
        for o_left, o_top, o_side in others
    )


def place_boxes(
    alpha: np.ndarray,
    difference: np.ndarray,
    blur: np.ndarray,
    count: int,
    nearer: np.ndarray | None = None,
) -> list[tuple[list[int], float]]:
    """Up to ``count`` boxes on the edge of ``alpha``, best first, clear of each other,
    and away from ``nearer``, the alpha of the objects in front of it."""
    from score import EDGE_STEP, edge_band  # the scoring script beside this one

    band = edge_band([alpha], BAND)
    if nearer is not None:
        band &= ~(edge_band([nearer], BAND) | (nearer > EDGE_STEP))
    band = band.astype(np.float64)
    tried = []
    for side in SIDES:
        score = box_scores(alpha, band, difference, blur, side)
        if nearer is not None:
            held = box_sums(nearer, side) / float(side * side)
            score = np.where(held > NEARER_MAX, 0.0, score)
        score = score[::STRIDE, ::STRIDE]
        tops, lefts = np.nonzero(score > 0)
        tried += [
            (float(score[t, x]), [int(x) * STRIDE, int(t) * STRIDE, side])
            for t, x in zip(tops, lefts, strict=True)
        ]
    boxes: list[tuple[list[int], float]] = []
    for value, box in sorted(tried, key=lambda x: -x[0]):
        if _clear(box, [b for b, _ in boxes]):
            boxes.append((box, value))
            if len(boxes) == count:
                break
    return boxes


def _read(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.float32)


def focus_alpha(
    pages: list[np.ndarray], focus: int | None, order: list[int] | None = None
) -> tuple[np.ndarray, np.ndarray | None]:
    """The alpha of the object in focus, or of every object when none is, and the alpha of
    the objects in front of it, or ``None``.

    The pages are recorded before occlusion, so the focused object's page also holds what a
    nearer object hides. ``order``, the frame's paint order far to near, takes that away:
    an edge under a blurred object in front is not the focused object's to show.
    """
    if focus is None or not 0 <= focus < len(pages):
        return np.max(pages, axis=0), None
    alpha = pages[focus]
    if order is None or focus not in order:
        return alpha, None
    nearer = [pages[page] for page in order[order.index(focus) + 1 :]]
    for page in nearer:
        alpha = alpha * (1.0 - page)
    return alpha, (np.max(nearer, axis=0) if nearer else None)


def candidates(
    image: Callable[[str, str], np.ndarray],
    alpha: Callable[[str], tuple[np.ndarray, np.ndarray | None]],
    frames: list[str],
    count: int,
) -> dict[str, dict]:
    """The candidate sheets of one sequence, by id.

    ``image(method, frame)`` reads a method's frame and ``alpha(frame)`` the alpha of the
    object whose edge the boxes go on, with that of the objects in front of it, as
    ``focus_alpha`` returns them.
    """
    per_frame = []
    for frame in frames:
        ours = image("ours", frame)
        difference = np.mean(
            [np.abs(image(m, frame) - ours).mean(axis=2) for m in PLACING], axis=0
        )
        blur = np.abs(image("all_in_focus", frame) - ours).mean(axis=2)
        focused, nearer = alpha(frame)
        boxes = place_boxes(focused, difference, blur, 3, nearer)
        if len(boxes) >= 2:  # a sheet holds two boxes
            per_frame.append((sum(v for _, v in boxes[:2]), frame, boxes))
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


def streams_of(seq: Path) -> dict[str, str]:
    """Each method's stream in ``seq``, MPIB's the linear one when it has no gamma one."""
    streams = {name: stream for name, stream, _ in METHODS}
    if not (seq / streams["mpib"]).is_dir():
        streams["mpib"] = MPIB_LINEAR
    return streams


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
    from video_bokeh.core._streams import read_alpha_tiff, read_paint_order

    for seq in list_sequences(data_root, None):
        streams = streams_of(seq)
        frames = [Path(n).stem for n in frame_names(seq)]
        record = seq / "bokeh" / "focus.json"
        focus = (
            json.loads(record.read_text()).get("object") if record.is_file() else None
        )

        def image(
            method: str,
            frame: str,
            seq: Path = seq,
            streams: dict[str, str] = streams,
        ) -> np.ndarray:
            return _read(seq / streams[method] / f"{frame}.png")

        painted = seq / "layers" / "paint_order.json"
        orders = (
            dict(zip(frames, read_paint_order(painted), strict=True))
            if painted.is_file()
            else {}
        )

        def alpha(
            frame: str,
            seq: Path = seq,
            focus: int | None = focus,
            orders: dict[str, list[int]] = orders,
        ) -> tuple[np.ndarray, np.ndarray | None]:
            pages = read_alpha_tiff(seq / "alpha" / f"{frame}.tif")
            return focus_alpha(pages, focus, orders.get(frame))

        sheets = candidates(image, alpha, frames, count)
        kept = frames if every_frame else sorted({s["frame"] for s in sheets.values()})
        target = out / seq.name
        target.mkdir(parents=True, exist_ok=True)
        for frame in kept:
            for name, stream in streams.items():
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
            if kept and not (folder / "sheets" / f"{sheet_id}.png").exists():
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
    s.add_argument(
        "--kept", action="store_true", help="only the candidates still in sheets/"
    )
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
