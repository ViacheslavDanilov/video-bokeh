"""The layer-wise bokeh renderer, in Stage C.

Reads each sequence's layers, its alpha masks and its disparity, and writes its bokeh
losslessly at the sequence's own size. Like every Stage C renderer it never reads the
library, so a sequence written without ``scenes.generate --layers`` is refused. It runs
on the CPU unless ``VIDEO_BOKEH_LAYERED_DEVICE`` names ``cuda`` or ``mps``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import numpy as np
import torch
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
)
from video_bokeh.layered import GAMMA, RADIUS_STEP, render_bokeh
from video_bokeh.library._device import select_device
from video_bokeh.render._stream import write_bokeh

_DEVICE = "VIDEO_BOKEH_LAYERED_DEVICE"
#: Frames rendered at once. Eight 1024-pixel frames with five objects hold about 1 GiB
#: of layers; a whole 80-frame sequence would hold ten.
_CHUNK = 8


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
        device = select_device(os.environ.get(_DEVICE, "cpu"))
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
            frames = _render(seq, names, zf, strength, device)
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
            [page > 0.5 for page in read_alpha_tiff(seq / "alpha" / _tif(name))],
            read_disparity_png(seq / "disparity" / name),
        )
        for name in names
    ]
    return focus_track(stats, focus_seed(sequence_seed(seq), seq.name))


def _render(
    seq: Path,
    names: list[str],
    zf: list[float],
    strength: float,
    device: torch.device,
) -> Iterator[Image.Image]:
    """Each frame's bokeh, rendered ``_CHUNK`` frames at a time."""
    orders = read_paint_order(seq / "layers" / "paint_order.json")
    for start in range(0, len(names), _CHUNK):
        chunk = names[start : start + _CHUNK]
        frames = [_read_frame(seq, name) for name in chunk]
        background, background_disparity, rgbs, alphas, disparities = (
            torch.from_numpy(np.stack(part)).to(device)
            for part in zip(*frames, strict=True)
        )
        out = render_bokeh(
            background,
            background_disparity,
            rgbs,
            alphas,
            disparities,
            torch.tensor(orders[start : start + len(chunk)], device=device),
            torch.tensor(zf[start : start + len(chunk)], device=device),
            strength,
        )
        pixels = (
            (out.permute(0, 2, 3, 1).cpu().numpy() * 255.0).round().astype(np.uint8)
        )
        for frame in pixels:
            yield Image.fromarray(frame, "RGB")


def _read_frame(seq: Path, name: str) -> tuple[np.ndarray, ...]:
    """One frame's layers as the renderer takes them, colours in ``[0, 1]``.

    Background (3, H, W), its disparity (1, H, W), object colours (N, 3, H, W), alpha
    masks (N, H, W) and object disparities (N, H, W).
    """
    layers = seq / "layers"
    with Image.open(layers / "background" / name) as im:
        background = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
    colours = np.stack(read_rgb_tiff(layers / "objects" / _tif(name))) / 255.0
    return (
        background.transpose(2, 0, 1),
        read_disparity_png(layers / "background_disparity" / name)[None],
        colours.transpose(0, 3, 1, 2).astype(np.float32),
        np.stack(read_alpha_tiff(seq / "alpha" / _tif(name))),
        np.stack(read_disparity_tiff(layers / "objects_disparity" / _tif(name))),
    )


def _tif(name: str) -> str:
    return f"{Path(name).stem}.tif"
