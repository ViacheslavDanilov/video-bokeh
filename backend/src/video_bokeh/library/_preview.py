"""The preview figure of a published library: what its items hold, and what Stage B makes.

Three rows, about 1600 pixels wide: two foregrounds as ``rgb.png`` over a checkerboard,
``alpha.png`` and ``depth.png`` inside the matte; three backgrounds as ``rgb.png`` and ``depth.png``; and
one frame that Stage B generates from the library, all-in-focus, disparity and bokeh.
Disparity is drawn with Spectral_r, near red and far violet, as Depth Anything V2's figures
draw it. The items are spread evenly over the sorted ids, and the frame comes from a fixed
seed, so the same library always gives the same figure.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from video_bokeh.core._library import (
    list_backgrounds,
    list_foregrounds,
    load_background,
    load_foreground,
)
from video_bokeh.preview._colormap import apply_colormap

#: Side of a small panel, and the gap around every panel, in pixels.
PANEL = 256
GAP = 8
#: Six small panels to a row: two foregrounds of three, or three backgrounds of two.
COLUMNS = 6
WIDTH = COLUMNS * PANEL + (COLUMNS + 1) * GAP
#: A generated frame's panel spans two small ones and the gap between them.
FRAME = 2 * PANEL + GAP
CAPTION = 22
MAX_BYTES = 10**6
#: The sequence the generated frame comes from.
SEED = 0

_INK = (40, 40, 40)
_PAPER = (255, 255, 255)
#: Where a foreground's matte is 0, so its disparity map is not drawn.
_OUTSIDE = (230, 230, 230)


def _evenly(ids: list[str], n: int) -> list[str]:
    """``n`` ids from the middles of ``n`` equal stretches of ``ids``."""
    return [ids[(2 * k + 1) * len(ids) // (2 * n)] for k in range(min(n, len(ids)))]


def _square(image: Image.Image, side: int) -> Image.Image:
    return image.resize((side, side), Image.Resampling.LANCZOS)


def _checkerboard(side: int, cell: int = 16) -> Image.Image:
    y, x = np.indices((side, side)) // cell
    board = np.where((x + y) % 2 == 0, 204, 238).astype(np.uint8)
    return Image.fromarray(np.stack([board] * 3, axis=-1))


def _disparity(disparity: np.ndarray, side: int) -> Image.Image:
    return _square(Image.fromarray(apply_colormap(disparity)), side)


def _foreground(library_root: Path, asset_id: str) -> list[tuple[str, Image.Image]]:
    fg = load_foreground(library_root, asset_id)
    cutout = _square(fg.rgb, PANEL)
    board = _checkerboard(PANEL)
    board.paste(cutout, mask=cutout.getchannel("A"))
    alpha = Image.fromarray((fg.alpha * 255).round().astype(np.uint8))
    return [
        ("foreground rgb.png", board),
        ("alpha.png", _square(alpha, PANEL).convert("RGB")),
        ("depth.png inside the matte", _matted(fg.depth, fg.alpha)),
    ]


def _matted(disparity: np.ndarray, alpha: np.ndarray) -> Image.Image:
    """Disparity where the matte is above 0, the only part Stage B reads; gray elsewhere."""
    colored = np.where(alpha[..., None] > 0, apply_colormap(disparity), _OUTSIDE)
    return _square(Image.fromarray(colored.astype(np.uint8)), PANEL)


def _background(library_root: Path, asset_id: str) -> list[tuple[str, Image.Image]]:
    bg = load_background(library_root, asset_id)
    return [
        ("background rgb.png", _square(bg.rgb, PANEL)),
        ("depth.png", _disparity(bg.depth, PANEL)),
    ]


def _frame(library_root: Path) -> list[tuple[str, Image.Image]]:
    """One frame of the sequence ``SEED`` names, with its bokeh, from Stage B's stream."""
    from video_bokeh.loader import SequenceStream

    stream = SequenceStream(
        library_root,
        n_frames=1,
        size=FRAME,
        n_objects_min=2,
        n_objects_max=3,
        seed=SEED,
        streams=("rgb", "disparity", "bokeh"),
    )
    item = next(iter(stream))

    def color(key: str) -> Image.Image:
        rgb = item[key][0].permute(1, 2, 0).numpy()
        return Image.fromarray((rgb * 255).round().astype(np.uint8))

    return [
        ("generated frame: all-in-focus", color("rgb")),
        ("disparity", _disparity(item["disparity"][0, 0].numpy(), FRAME)),
        ("bokeh", color("bokeh")),
    ]


def _row(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    top: int,
    panels: list[tuple[str, Image.Image]],
) -> int:
    """Paste ``panels`` left to right under their captions; return the next row's top."""
    left = GAP
    for caption, image in panels:
        draw.text((left, top + 3), caption, fill=_INK, font=font)
        canvas.paste(image, (left, top + CAPTION))
        left += image.width + GAP
    return top + CAPTION + max(image.height for _, image in panels) + GAP


def _legend(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    top: int,
) -> None:
    """A Spectral_r bar from far to near, centered under the rows, at ``top``."""
    width, height = 320, 12
    ramp = np.tile(np.linspace(0.0, 1.0, width, dtype=np.float32), (height, 1))
    left = (canvas.width - width) // 2
    canvas.paste(Image.fromarray(apply_colormap(ramp)), (left, top + 4))
    draw.text((left - 8, top + 1), "disparity: far", fill=_INK, font=font, anchor="ra")
    draw.text((left + width + 8, top + 1), "near", fill=_INK, font=font, anchor="la")


def write_preview(library_root: Path, path: Path) -> None:
    """Draw the preview of the library at ``library_root`` into the JPEG ``path``.

    The frame needs torch, which the ``library`` and ``loader`` extras install.
    """
    rows = [
        [
            p
            for i in _evenly(list_foregrounds(library_root), 2)
            for p in _foreground(library_root, i)
        ],
        [
            p
            for i in _evenly(list_backgrounds(library_root), 3)
            for p in _background(library_root, i)
        ],
        _frame(library_root),
    ]
    legend = 28
    height = (
        GAP + sum(CAPTION + max(im.height for _, im in r) + GAP for r in rows) + legend
    )
    canvas = Image.new("RGB", (WIDTH, height), _PAPER)
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=15)
    top = GAP
    for row in rows:
        top = _row(canvas, draw, font, top, row)
    _legend(canvas, draw, font, top)
    path.parent.mkdir(parents=True, exist_ok=True)
    for quality in range(90, 40, -5):
        buffer = io.BytesIO()
        canvas.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True)
        if buffer.tell() <= MAX_BYTES:
            break
    path.write_bytes(buffer.getvalue())
