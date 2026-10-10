"""A sequence's bokeh, frame by frame, from its layers wherever they come from.

The dataset writer and the API render frames with their layers in memory; Stage C reads
them back from ``layers/``. Both hand this module the same per-frame layers, and it renders
them a few frames at a time, so a long sequence never holds its layers whole.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

import numpy as np
import torch
from PIL import Image

from video_bokeh.layered._renderer import render_bokeh
from video_bokeh.library._device import select_device
from video_bokeh.scenes._compositor import RenderedFrame

#: The renderer's name, as ``focus.json`` and Stage C's ``--renderer`` give it.
RENDERER = "layered"
#: Names the torch device that renders a sequence's bokeh: ``cuda``, ``mps`` or ``cpu``.
DEVICE_VARIABLE = "VIDEO_BOKEH_LAYERED_DEVICE"
#: Frames rendered at once. Eight 1024-pixel frames with five objects hold about 1 GiB of
#: layers; a whole 80-frame sequence would hold ten.
CHUNK = 8


@dataclass(frozen=True)
class LayeredFrame:
    """One frame's layers as the renderer takes them, colours in ``[0, 1]``."""

    background: np.ndarray  # (3, H, W)
    background_disparity: np.ndarray  # (1, H, W)
    object_rgbs: np.ndarray  # (N, 3, H, W)
    object_alphas: np.ndarray  # (N, H, W)
    object_disparities: np.ndarray  # (N, H, W)
    paint_order: list[int]  # object indices, far to near


def layered_frame(frame: RenderedFrame) -> LayeredFrame:
    """A frame Stage B rendered with its layers, as the renderer takes it."""
    layers = frame.layers
    if layers is None:
        raise ValueError("the frame was rendered without its layers")
    return LayeredFrame(
        background=layers.background_rgb.transpose(2, 0, 1) / 255.0,
        background_disparity=layers.background_disparity[None],
        object_rgbs=np.stack(layers.object_rgbs).transpose(0, 3, 1, 2) / 255.0,
        object_alphas=np.stack(frame.object_alphas),
        object_disparities=np.stack(layers.object_disparities),
        paint_order=layers.paint_order,
    )


def bokeh_device() -> torch.device:
    """The device ``VIDEO_BOKEH_LAYERED_DEVICE`` names, the CPU when unset or absent."""
    return select_device(os.environ.get(DEVICE_VARIABLE, "cpu"))


def render_sequence(
    frames: Iterable[LayeredFrame],
    focus_disparity: Sequence[float],
    strength: float,
    device: torch.device,
) -> Iterator[Image.Image]:
    """Each frame's bokeh as an RGB image, rendered ``CHUNK`` frames at a time."""
    chunk: list[LayeredFrame] = []
    done = 0
    for frame in frames:
        chunk.append(frame)
        if len(chunk) == CHUNK:
            yield from _render_chunk(chunk, focus_disparity[done:], strength, device)
            done += len(chunk)
            chunk = []
    if chunk:
        yield from _render_chunk(chunk, focus_disparity[done:], strength, device)


def _render_chunk(
    frames: list[LayeredFrame],
    focus_disparity: Sequence[float],
    strength: float,
    device: torch.device,
) -> Iterator[Image.Image]:
    def stacked(arrays: list[np.ndarray]) -> torch.Tensor:
        return torch.from_numpy(np.stack(arrays).astype(np.float32)).to(device)

    out = render_bokeh(
        stacked([f.background for f in frames]),
        stacked([f.background_disparity for f in frames]),
        stacked([f.object_rgbs for f in frames]),
        stacked([f.object_alphas for f in frames]),
        stacked([f.object_disparities for f in frames]),
        torch.tensor([f.paint_order for f in frames], device=device),
        torch.tensor(list(focus_disparity[: len(frames)]), device=device),
        strength,
    )
    pixels = (out.permute(0, 2, 3, 1).cpu().numpy() * 255.0).round().astype(np.uint8)
    for frame in pixels:
        yield Image.fromarray(frame, "RGB")
