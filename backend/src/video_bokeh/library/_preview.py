"""The preview of a published library: what its items hold, and what Stage B makes of them.

The figure, about 2,500 pixels wide, has two sections under a heading and a rule. Up to
four foregrounds sit two to a row, each on a blue-tinted card as ``rgb.png`` over a
checkerboard, ``alpha.png`` and ``depth.png`` inside the matte; up to three backgrounds sit
in one row, each on a warm-tinted card as ``rgb.png`` and ``depth.png``. The video plays
sequences that Stage B generates from the library at 1024 pixels, in the six panes the
demo shows: all in focus, disparity and the objects' mattes over bokeh, forward optical
flow and occlusion, with a dot for each sequence under them. Disparity is drawn with
Spectral_r, near red and far violet, as Depth Anything V2's figures draw it. Unless the ids
are given, the items are spread evenly over the sorted ids; the sequences come from fixed
seeds. The same library and arguments always give the same preview. ``depth_preview``
draws one item's disparity the same way, for the shards ``pack`` writes.
"""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from video_bokeh.core._library import (
    FOREGROUNDS,
    list_backgrounds,
    list_foregrounds,
    load_background,
    load_foreground,
)
from video_bokeh.preview._colormap import apply_colormap

#: Side of a foreground's panel, the gap between panels, a card's padding, the gap between
#: cards and the page's margin, in pixels.
PANEL = 384
GAP = 10
PAD = 16
CARD_GAP = 24
MARGIN = 32
#: Two foreground cards to a row, each of three panels.
_FG_CARD = 3 * PANEL + 2 * GAP + 2 * PAD
WIDTH = 2 * _FG_CARD + CARD_GAP + 2 * MARGIN
#: Three background cards to a row, each of two panels, as wide in all as the foregrounds.
BG_PANEL = (WIDTH - 2 * MARGIN - 2 * CARD_GAP - 3 * (GAP + 2 * PAD)) // 6
#: A panel's caption, a section's heading with its rule, and the legend, in pixels high.
CAPTION = 32
HEADING = 70
LEGEND = 56
MAX_BYTES = 3 * 10**6
#: The figure's items, unless they are given.
N_FOREGROUNDS = 4
N_BACKGROUNDS = 3
#: The video's sequences, unless their seeds are given.
SEEDS = (0, 1, 2)
#: Side of a video panel, the frames of each sequence, and the frame rate. A sequence's
#: motion spans its frames whatever their number, so more frames play it more smoothly.
VIDEO_PANEL = 1024
VIDEO_FRAMES = 96
FPS = 24
#: The video's gap between panels, its caption band and the band of its dots.
VIDEO_GAP = 16
VIDEO_CAPTION = 64
VIDEO_DOTS = 36

_INK = (31, 35, 40)
_MUTED = (110, 118, 128)
_RULE = (214, 218, 224)
#: The cards: blue-tinted for foregrounds, warm-tinted for backgrounds, one edge for both.
_FG_FILL = (246, 249, 255)
_BG_FILL = (255, 250, 243)
_CARD_EDGE = (205, 219, 245)
_PAPER = (255, 255, 255)
#: The matte a foreground's disparity is drawn from: Stage A's default ``--alpha-threshold``,
#: where its trusted core starts. Below it, the faint halo of MAGICK's mattes is drawn gray.
_DRAWN_ALPHA = 0.04
#: The gray a foreground's disparity panel shows outside the drawn matte.
_OUTSIDE = (232, 232, 232)
#: Each panel's caption: what it shows, then the file it shows, muted.
_FG_CAPTIONS = (
    ("Color", "rgb.png"),
    ("Matte", "alpha.png"),
    ("Disparity", "depth.png"),
)
_BG_CAPTIONS = (("Color", "rgb.png"), ("Disparity", "depth.png"))
#: The video's panes, three to a row, named as the demo names them.
_VIDEO_CAPTIONS = (
    "All in focus",
    "Disparity",
    "Alpha",
    "Bokeh",
    "Optical flow",
    "Occlusion",
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _evenly(ids: list[str], n: int) -> list[str]:
    """``n`` ids from the middles of ``n`` equal stretches of ``ids``."""
    return [ids[(2 * k + 1) * len(ids) // (2 * n)] for k in range(min(n, len(ids)))]


def _square(image: Image.Image, side: int) -> Image.Image:
    return image.resize((side, side), Image.Resampling.LANCZOS)


def _checkerboard(side: int, cell: int = 16) -> Image.Image:
    y, x = np.indices((side, side)) // cell
    board = np.where((x + y) % 2 == 0, 204, 238).astype(np.uint8)
    return Image.fromarray(np.stack([board] * 3, axis=-1))


def _matted(alpha: np.ndarray, depth: np.ndarray) -> np.ndarray:
    """A foreground's colored disparity where its matte reaches ``_DRAWN_ALPHA``, gray
    elsewhere, as uint8 RGB."""
    colored = np.where(
        alpha[..., None] >= _DRAWN_ALPHA, apply_colormap(depth), _OUTSIDE
    )
    return colored.astype(np.uint8)


def depth_preview(library_root: Path, kind: str, asset_id: str) -> bytes:
    """An item's disparity in color, at the item's size, as JPEG bytes.

    A foreground's is drawn where its matte reaches ``_DRAWN_ALPHA``, as the figure draws
    it; a background's covers the whole photo. ``pack`` puts it in the shards for the Hub's
    viewer, and nothing reads it back.
    """
    if kind == FOREGROUNDS:
        fg = load_foreground(library_root, asset_id)
        rgb = _matted(fg.alpha, fg.depth)
    else:
        rgb = apply_colormap(load_background(library_root, asset_id).depth)
    buffer = io.BytesIO()
    Image.fromarray(rgb).save(buffer, "JPEG", quality=88)
    return buffer.getvalue()


def _foreground(library_root: Path, asset_id: str) -> list[Image.Image]:
    fg = load_foreground(library_root, asset_id)
    cutout = _square(fg.rgb, PANEL)
    board = _checkerboard(PANEL)
    board.paste(cutout, mask=cutout.getchannel("A"))
    alpha = Image.fromarray((fg.alpha * 255).round().astype(np.uint8))
    return [
        board,
        _square(alpha, PANEL).convert("RGB"),
        _square(Image.fromarray(_matted(fg.alpha, fg.depth)), PANEL),
    ]


def _background(library_root: Path, asset_id: str) -> list[Image.Image]:
    bg = load_background(library_root, asset_id)
    return [
        _square(bg.rgb, BG_PANEL),
        _square(Image.fromarray(apply_colormap(bg.depth)), BG_PANEL),
    ]


def _heading(draw: ImageDraw.ImageDraw, top: int, title: str, note: str) -> int:
    """A section's title, a muted note after it and a rule under both; return the next top."""
    title_font = _font(34)
    # Pillow's own font has no bold, so a thin stroke in the ink stands in for it.
    draw.text(
        (MARGIN, top),
        title,
        fill=_INK,
        font=title_font,
        stroke_width=1,
        stroke_fill=_INK,
    )
    left = MARGIN + draw.textlength(title, font=title_font) + 16
    draw.text((left, top + 10), note, fill=_MUTED, font=_font(22))
    draw.line((MARGIN, top + 52, WIDTH - MARGIN, top + 52), fill=_RULE, width=2)
    return top + HEADING


def _card(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    panels: list[Image.Image],
    captions: Sequence[tuple[str, str]],
    fill: tuple[int, int, int],
) -> int:
    """Panels side by side on a rounded card, each under its caption; return its width."""
    side = panels[0].width
    width = len(panels) * side + (len(panels) - 1) * GAP + 2 * PAD
    height = CAPTION + side + 2 * PAD
    draw.rounded_rectangle(
        (left, top, left + width, top + height),
        12,
        fill=fill,
        outline=_CARD_EDGE,
        width=2,
    )
    font = _font(20)
    for k, (panel, (what, name)) in enumerate(zip(panels, captions, strict=True)):
        x = left + PAD + k * (side + GAP)
        draw.text((x, top + PAD), what, fill=_INK, font=font)
        draw.text(
            (x + draw.textlength(what, font=font) + 8, top + PAD),
            name,
            fill=_MUTED,
            font=font,
        )
        canvas.paste(panel, (x, top + PAD + CAPTION))
    return width


def _legend(canvas: Image.Image, draw: ImageDraw.ImageDraw, top: int) -> None:
    """A Spectral_r bar from far to near, centered under the sections, at ``top``."""
    width, height = 320, 14
    font = _font(20)
    ramp = np.tile(np.linspace(0.0, 1.0, width, dtype=np.float32), (height, 1))
    left = (canvas.width - width) // 2
    middle = top + height // 2
    canvas.paste(Image.fromarray(apply_colormap(ramp)), (left, top))
    draw.text((left - 10, middle), "far", fill=_MUTED, font=font, anchor="rm")
    draw.text((left + width + 10, middle), "near", fill=_MUTED, font=font, anchor="lm")


def write_preview(
    library_root: Path,
    path: Path,
    foregrounds: Sequence[str] | None = None,
    backgrounds: Sequence[str] | None = None,
) -> None:
    """Draw the figure of the library at ``library_root`` into the JPEG ``path``.

    ``foregrounds``, up to four ids, and ``backgrounds``, up to three, pick the items.
    """
    all_fg, all_bg = list_foregrounds(library_root), list_backgrounds(library_root)
    fg_ids = list(foregrounds or _evenly(all_fg, N_FOREGROUNDS))
    bg_ids = list(backgrounds or _evenly(all_bg, N_BACKGROUNDS))
    if len(fg_ids) > N_FOREGROUNDS or len(bg_ids) > N_BACKGROUNDS:
        raise SystemExit(
            f"the figure holds {N_FOREGROUNDS} foregrounds and {N_BACKGROUNDS} "
            "backgrounds at most"
        )
    fg_rows = (len(fg_ids) + 1) // 2
    fg_card = CAPTION + PANEL + 2 * PAD
    bg_card = CAPTION + BG_PANEL + 2 * PAD
    height = (
        MARGIN
        + HEADING
        + fg_rows * (fg_card + CARD_GAP)
        + 16
        + HEADING
        + bg_card
        + LEGEND
    )
    canvas = Image.new("RGB", (WIDTH, height), _PAPER)
    draw = ImageDraw.Draw(canvas)
    top = _heading(
        draw,
        MARGIN,
        "Foregrounds",
        f"{len(all_fg):,} cut-out objects, each with a matte and disparity",
    )
    for k, asset_id in enumerate(fg_ids):
        left = MARGIN + (k % 2) * (_FG_CARD + CARD_GAP)
        row_top = top + (k // 2) * (fg_card + CARD_GAP)
        _card(
            canvas,
            draw,
            left,
            row_top,
            _foreground(library_root, asset_id),
            _FG_CAPTIONS,
            _FG_FILL,
        )
    top += fg_rows * (fg_card + CARD_GAP) + 16
    top = _heading(
        draw, top, "Backgrounds", f"{len(all_bg):,} photos, each with disparity"
    )
    left = MARGIN
    for asset_id in bg_ids:
        width = _card(
            canvas,
            draw,
            left,
            top,
            _background(library_root, asset_id),
            _BG_CAPTIONS,
            _BG_FILL,
        )
        left += width + CARD_GAP
    _legend(canvas, draw, top + bg_card + 22)
    path.parent.mkdir(parents=True, exist_ok=True)
    for quality in range(92, 40, -4):
        buffer = io.BytesIO()
        canvas.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True)
        if buffer.tell() <= MAX_BYTES:
            break
    path.write_bytes(buffer.getvalue())


def _sequence(library_root: Path, seed: int) -> Iterator[list[np.ndarray]]:
    """The six panes of each frame of Stage B's sequence ``seed``, colored as the demo does.

    Optical flow is colored at the sequence's fastest motion, so its frames share one
    scale, and occlusion grays the frame and draws what the next frame hides in cyan. The
    last frame has neither, so its flow is still and its occlusion plain gray. A seed whose
    objects cannot be placed is refused, so the video plays the seeds it names.
    """
    from video_bokeh.loader import SequenceStream
    from video_bokeh.preview._flow import flow_to_rgb
    from video_bokeh.preview._masks import render_object_masks
    from video_bokeh.preview.pack import (
        _CYAN,
        _LUMA,
        _OVERLAY_BRIGHTNESS,
        _OVERLAY_OPACITY,
    )

    stream = SequenceStream(
        library_root,
        n_frames=VIDEO_FRAMES,
        size=VIDEO_PANEL,
        n_objects_min=2,
        n_objects_max=4,
        seed=seed,
        streams=("rgb", "disparity", "object_alphas", "bokeh", "flow", "occlusion"),
    )
    item = next(iter(stream))
    if item["seed"] != seed:
        raise SystemExit(f"seed {seed} places no sequence; take another")

    def color(key: str) -> np.ndarray:
        rgb = item[key].permute(0, 2, 3, 1).numpy()
        return (rgb * 255).round().astype(np.uint8)

    rgb, bokeh = color("rgb"), color("bokeh")
    disparity = item["disparity"][:, 0].numpy()
    mattes = item["object_alphas"][:, : item["n_objects"]].numpy()
    flow = item["flow"].permute(0, 2, 3, 1).numpy()
    top_speed = float(np.hypot(flow[..., 0], flow[..., 1]).max()) or 1.0
    still = np.zeros_like(flow[0])
    occluded = item["occlusion"][:, 0].numpy() > 0.5
    for t in range(len(rgb)):
        gray = np.repeat((rgb[t] @ _LUMA * _OVERLAY_BRIGHTNESS)[..., None], 3, -1)
        if t < len(occluded):
            cyan = gray * (1 - _OVERLAY_OPACITY) + _CYAN * _OVERLAY_OPACITY
            gray = np.where(occluded[t][..., None], cyan, gray)
        yield [
            rgb[t],
            apply_colormap(disparity[t]),
            render_object_masks(list(mattes[t])),
            bokeh[t],
            flow_to_rgb(flow[t] if t < len(flow) else still, top_speed),
            gray.round().astype(np.uint8),
        ]


def write_video(library_root: Path, path: Path, seeds: Sequence[int] = SEEDS) -> None:
    """Write the sequences ``seeds`` of the library at ``library_root`` to the MP4 ``path``.

    Each frame shows the six panes in two rows of three under their captions, and a dot
    for each sequence, the one playing filled. The sequences need torch and the encoder
    imageio's ffmpeg, which the ``library`` extra installs.
    """
    import imageio.v2 as iio

    row = VIDEO_CAPTION + VIDEO_PANEL
    width = 3 * VIDEO_PANEL + 4 * VIDEO_GAP
    height = 2 * row + VIDEO_DOTS
    font = _font(30)
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

    def corner(k: int) -> tuple[int, int]:
        """The top-left of pane ``k``, three to a row."""
        return VIDEO_GAP + (k % 3) * (VIDEO_PANEL + VIDEO_GAP), (k // 3) * row

    with writer:
        for n, seed in enumerate(seeds):
            page = Image.new("RGB", (width, height), _PAPER)
            draw = ImageDraw.Draw(page)
            for k, caption in enumerate(_VIDEO_CAPTIONS):
                left, top = corner(k)
                draw.text(
                    (left + VIDEO_PANEL // 2, top + VIDEO_CAPTION // 2),
                    caption,
                    fill=_INK,
                    font=font,
                    anchor="mm",
                )
            middle = 2 * row + VIDEO_DOTS // 2
            for k in range(len(seeds)):
                x = width // 2 + round((k - (len(seeds) - 1) / 2) * 28)
                fill = _INK if k == n else _RULE
                draw.ellipse((x - 7, middle - 7, x + 7, middle + 7), fill=fill)
            blank = np.asarray(page)
            for panes in _sequence(library_root, seed):
                frame = blank.copy()
                for k, pane in enumerate(panes):
                    left, top = corner(k)
                    frame[
                        top + VIDEO_CAPTION : top + row, left : left + VIDEO_PANEL
                    ] = pane
                writer.append_data(frame)
