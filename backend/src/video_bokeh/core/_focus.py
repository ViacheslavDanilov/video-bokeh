"""Which object a sequence's bokeh focuses on, and each frame's in-focus disparity.

One rule for every bokeh renderer and the training loader: one object, drawn with odds
proportional to the area it holds alone on screen; in every frame, the mean disparity over
the pixels it holds alone. A frame where it is hidden keeps the last focus seen, and frames
before it is first seen take the first. A sequence with no object to draw focuses each
frame on the mean disparity under all its objects, or over the whole frame if none shows.

Only the pixels an object holds alone count, because the alpha masks are recorded before
occlusion: where two overlap, the disparity may belong to either.
"""

from __future__ import annotations

import zlib
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FrameFocus:
    """What the rule needs from one frame, without keeping its masks."""

    #: Per object, the pixels it holds alone.
    areas: list[int]
    #: Per object, the mean disparity over those pixels, or None where it is hidden.
    means: list[float | None]
    #: The mean disparity under all the objects' masks, or over the frame if none shows.
    fallback: float


def frame_focus(masks: Sequence[np.ndarray], disparity: np.ndarray) -> FrameFocus:
    """Measure one frame. ``masks`` are boolean, one per object in page order."""
    visible = visible_masks(list(masks))
    union = np.zeros(disparity.shape, dtype=bool)
    for mask in masks:
        union |= mask
    return FrameFocus(
        areas=[int(v.sum()) for v in visible],
        means=[float(disparity[v].mean()) if v.any() else None for v in visible],
        fallback=float(disparity[union].mean() if union.any() else disparity.mean()),
    )


def focus_track(
    frames: Sequence[FrameFocus],
    seed: int,
) -> tuple[int | None, list[float]]:
    """The object the focus follows, or None, and every frame's in-focus disparity."""
    n_objects = max((len(f.areas) for f in frames), default=0)
    totals = [
        sum(f.areas[i] for f in frames if i < len(f.areas)) / len(frames)
        for i in range(n_objects)
    ]
    chosen = choose_focus_object(totals, seed)
    if chosen is None:
        return None, [f.fallback for f in frames]
    means = [f.means[chosen] if chosen < len(f.means) else None for f in frames]
    first = next(z for z in means if z is not None)
    held: list[float] = []
    for z in means:
        first = z if z is not None else first
        held.append(first)
    return chosen, held


def focus_seed(scene_seed: int | None, name: str) -> int:
    """The seed of the focus draw.

    The scene's own seed, so a scene focuses on the same object wherever it is rendered:
    in a written dataset under any name, or in the training loader. A sequence that does
    not record its scene's seed falls back to its name.
    """
    return zlib.crc32(
        (f"focus:{scene_seed}" if scene_seed is not None else name).encode(),
    )


def choose_focus_object(areas: Sequence[float], seed: int) -> int | None:
    """One object, drawn with probability proportional to its area; None without any.

    By area rather than the largest: large objects are usually the near ones, so the
    largest would put the focus on the foreground almost every time. A tiny object in
    focus leaves next to nothing sharp, which the weighting makes rare.
    """
    weights = np.asarray(areas, dtype=np.float64)
    if weights.size == 0 or weights.sum() <= 0:
        return None
    rng = np.random.default_rng(seed)
    return int(rng.choice(weights.size, p=weights / weights.sum()))


def visible_masks(masks: list[np.ndarray]) -> list[np.ndarray]:
    """Each object's pixels that no other object's mask covers.

    Stage B writes each mask whole, before occlusion, and the disparity shows whichever
    object is nearest. Where two masks overlap, the disparity may belong to either, so
    only the pixels one mask holds alone are surely that object's. A small object in front
    of a large one, wholly inside its mask, reads as hidden then, as a covered one does.
    """
    visible = []
    for i, mask in enumerate(masks):
        others = np.zeros_like(mask)
        for j, other in enumerate(masks):
            if j != i:
                others |= other
        visible.append(mask & ~others)
    return visible
