"""The preview of a published library: what its items hold, and what Stage B makes of them.

The figure, about 1600 pixels wide, has two rows of two foregrounds, each as ``rgb.png``
over a checkerboard, ``alpha.png`` and ``depth.png`` inside the matte, and a row of three
backgrounds as ``rgb.png`` and ``depth.png``. The video plays sequences that Stage B
generates from the library, all-in-focus, disparity and bokeh side by side. Disparity is
drawn with Spectral_r, near red and far violet, as Depth Anything V2's figures draw it.
Unless the ids are given, the items are spread evenly over the sorted ids; the sequences
come from fixed seeds. The same library and arguments always give the same preview.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

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
CAPTION = 22
MAX_BYTES = 10**6
#: The figure's items, unless they are given.
N_FOREGROUNDS = 4
N_BACKGROUNDS = 3
#: The video's sequences, unless their seeds are given, and their frames.
SEEDS = (0, 1, 2)
#: Side of a video panel, the frames of each sequence, and the frame rate.
VIDEO_PANEL = 384
VIDEO_FRAMES = 48
FPS = 12

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


def _sequence(library_root: Path, seed: int) -> list[list[np.ndarray]]:
    """The all-in-focus, colored disparity and bokeh frames of Stage B's sequence ``seed``.

    A seed whose objects cannot be placed is refused, so the video plays the seeds it names.
    """
    from video_bokeh.loader import SequenceStream

    stream = SequenceStream(
        library_root,
        n_frames=VIDEO_FRAMES,
        size=VIDEO_PANEL,
        n_objects_min=2,
        n_objects_max=4,
        seed=seed,
        streams=("rgb", "disparity", "bokeh"),
    )
    item = next(iter(stream))
    if item["seed"] != seed:
        raise SystemExit(f"seed {seed} places no sequence; take another")

    def color(key: str) -> np.ndarray:
        rgb = item[key].permute(0, 2, 3, 1).numpy()
        return (rgb * 255).round().astype(np.uint8)

    disparity = item["disparity"][:, 0].numpy()
    return [
        list(frames)
        for frames in zip(
            color("rgb"),
            (apply_colormap(d) for d in disparity),
            color("bokeh"),
            strict=True,
        )
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


def write_preview(
    library_root: Path,
    path: Path,
    foregrounds: Sequence[str] | None = None,
    backgrounds: Sequence[str] | None = None,
) -> None:
    """Draw the figure of the library at ``library_root`` into the JPEG ``path``.

    ``foregrounds``, up to four ids, and ``backgrounds``, up to three, pick the items.
    """
    fg_ids = list(foregrounds or _evenly(list_foregrounds(library_root), N_FOREGROUNDS))
    bg_ids = list(backgrounds or _evenly(list_backgrounds(library_root), N_BACKGROUNDS))
    if len(fg_ids) > N_FOREGROUNDS or len(bg_ids) > N_BACKGROUNDS:
        raise SystemExit(
            f"the figure holds {N_FOREGROUNDS} foregrounds and {N_BACKGROUNDS} "
            "backgrounds at most"
        )
    rows = [
        [p for i in fg_ids[k : k + 2] for p in _foreground(library_root, i)]
        for k in range(0, len(fg_ids), 2)
    ]
    rows.append([p for i in bg_ids for p in _background(library_root, i)])
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


def write_video(library_root: Path, path: Path, seeds: Sequence[int] = SEEDS) -> None:
    """Write the sequences ``seeds`` of the library at ``library_root`` to the MP4 ``path``.

    Each frame shows all-in-focus, disparity and bokeh side by side, under their captions.
    The sequences need torch and the encoder imageio's ffmpeg, which the ``library`` extra
    installs.
    """
    import imageio.v2 as iio

    captions = ("all-in-focus", "disparity", "bokeh")
    width = 3 * VIDEO_PANEL + 4 * GAP
    height = CAPTION + VIDEO_PANEL + 2 * GAP
    header = Image.new("RGB", (width, height), _PAPER)
    draw = ImageDraw.Draw(header)
    font = ImageFont.load_default(size=15)
    for k, caption in enumerate(captions):
        draw.text(
            (GAP + k * (VIDEO_PANEL + GAP), GAP + 3), caption, fill=_INK, font=font
        )
    blank = np.asarray(header)
    path.parent.mkdir(parents=True, exist_ok=True)
    # `cast` because imageio's writer is typed as an abstract base class but the
    # concrete subclass exposes `append_data`.
    writer = cast(
        Any,
        iio.get_writer(
            path,
            fps=FPS,
            codec="libx264",
            quality=None,
            output_params=["-crf", "22", "-profile:v", "high"],
            pixelformat="yuv420p",
            macro_block_size=1,
        ),
    )
    top = GAP + CAPTION
    with writer:
        for seed in seeds:
            for panels in _sequence(library_root, seed):
                frame = blank.copy()
                for k, panel in enumerate(panels):
                    left = GAP + k * (VIDEO_PANEL + GAP)
                    frame[top : top + VIDEO_PANEL, left : left + VIDEO_PANEL] = panel
                writer.append_data(frame)
