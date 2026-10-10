"""The layer-wise bokeh renderer, in Stage C.

Reads each sequence's layers, its alpha masks and its disparity, and writes its bokeh
losslessly at the sequence's own size. Like every Stage C renderer it never reads the
library, so a sequence written without ``scenes.generate --layers`` is refused. It runs
on the CPU unless ``VIDEO_BOKEH_LAYERED_DEVICE`` names ``cuda`` or ``mps``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import numpy as np
from PIL import Image

from video_bokeh.bridge.any_to_bokeh import list_png_frames
from video_bokeh.core._focus import focus_seed, focus_track, frame_focus
from video_bokeh.core._seq_io import has_layers, sequence_seed
from video_bokeh.core._streams import (
    read_alpha_tiff,
    read_disparity_png,
    read_disparity_tiff,
    read_paint_order,
    read_rgb_tiff,
    write_bokeh,
)
from video_bokeh.layered import (
    GAMMA,
    RADIUS_STEP,
    LayeredFrame,
    bokeh_device,
    render_sequence,
)


class Layered:
    """The layer-wise renderer, with ``strength`` in any-to-bokeh's units of ``k``.

    With no ``focus_disparity``, the focus follows one object, drawn by area, as
    any-to-bokeh's does; ``bokeh/focus.json`` records which.
    """

    name: ClassVar[str] = "layered"
    #: It renders from the ``layers/`` stream; ``render.run --missing`` leaves out the
    #: sequences without it instead of handing them over.
    needs_layers: ClassVar[bool] = True

    def render(
        self,
        sequence_dirs: list[Path],
        strength: float,
        focus_disparity: float | None,
    ) -> None:
        missing = [seq.name for seq in sequence_dirs if not has_layers(seq)]
        if missing:
            raise ValueError(
                f"no complete layers/ in {', '.join(missing)}: the layered renderer "
                "needs them. Write them with video_bokeh.scenes.generate --layers.",
            )
        device = bokeh_device()
        for seq in sequence_dirs:
            names = [p.name for p in list_png_frames(seq / "all_in_focus")]
            focus_object, zf = _focus(seq, names, focus_disparity)
            record = {
                "object": focus_object,
                "zf": zf,
                "renderer": self.name,
                "strength": strength,
                "gamma": GAMMA,
                "radius_step": RADIUS_STEP,
            }
            frames = render_sequence(_read_frames(seq, names), zf, strength, device)
            write_bokeh(seq, zip(names, frames, strict=True), record)


def _focus(
    seq: Path,
    names: list[str],
    focus_disparity: float | None,
) -> tuple[int | None, list[float]]:
    if focus_disparity is not None:
        return None, [focus_disparity] * len(names)
    stats = [
        frame_focus(
            read_alpha_tiff(seq / "alpha" / _tif(name)),
            read_disparity_png(seq / "disparity" / name),
        )
        for name in names
    ]
    return focus_track(stats, focus_seed(sequence_seed(seq), seq.name))


def _read_frames(seq: Path, names: list[str]) -> Iterator[LayeredFrame]:
    """Each frame's layers as ``layers/`` and ``alpha/`` hold them, colours in [0, 1]."""
    layers = seq / "layers"
    orders = read_paint_order(layers / "paint_order.json")
    for name, order in zip(names, orders, strict=True):
        with Image.open(layers / "background" / name) as im:
            background = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
        colours = np.stack(read_rgb_tiff(layers / "objects" / _tif(name))) / 255.0
        yield LayeredFrame(
            background=background.transpose(2, 0, 1),
            background_disparity=read_disparity_png(
                layers / "background_disparity" / name,
            )[None],
            object_rgbs=colours.transpose(0, 3, 1, 2),
            object_alphas=np.stack(read_alpha_tiff(seq / "alpha" / _tif(name))),
            object_disparities=np.stack(
                read_disparity_tiff(layers / "objects_disparity" / _tif(name)),
            ),
            paint_order=order,
        )


def _tif(name: str) -> str:
    return f"{Path(name).stem}.tif"
