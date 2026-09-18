"""Unrestricted depth trajectories: a per-object disparity range over time.

An object's depth state at a frame is the interval [mind, maxd] its warped depth
map is remapped into. The interval at the end of the clip is derived from the
start interval and the scale ratio, never sampled: growing on screen by a factor
k must bring the object k times closer, which on the disparity axis (larger =
closer) means multiplying the interval by k. The assigned depth band constrains
only the start interval; every later frame is free.

See docs/superpowers/specs/2026-09-09-unrestricted-trajectories-design.md.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from video_bokeh.core._sequence_geometry import Pose, SampleConfig, sample_fg_pose

_MAX_DISPARITY = 1.0


@dataclass(frozen=True)
class DepthRange:
    """Disparity interval an object occupies at one frame. Larger = closer."""

    mind: float
    maxd: float

    @property
    def width(self) -> float:
        return self.maxd - self.mind

    @property
    def centre(self) -> float:
        return (self.mind + self.maxd) / 2.0

    def lerp(self, other: DepthRange, t: float) -> DepthRange:
        return DepthRange(
            mind=self.mind + (other.mind - self.mind) * t,
            maxd=self.maxd + (other.maxd - self.maxd) * t,
        )


def derive_end_range(
    start: DepthRange,
    scale_start: float,
    scale_end: float,
) -> DepthRange:
    """End-of-clip range implied by the scale ratio (depth-scale compatibility).

    Never sampled independently: this is the constraint that keeps the RGB and
    disparity streams telling the same story about the object's motion.

    Apparent size and disparity are both proportional to 1/z, so they move
    together: the ratio is ``scale_end / scale_start``, not its reciprocal. The
    approved research spec writes the reciprocal, but it derives the rule for
    depth-as-distance ("its depth must decrease by the factor k") and then
    applies the formula to mind/maxd, which this pipeline defines as disparity.
    Taken literally it makes an object that grows on screen recede in the
    disparity stream -- the exact RGB/disparity inconsistency this model
    removes.
    """
    if scale_start <= 1e-8:
        raise ValueError(f"scale_start must be positive, got {scale_start}")
    ratio = scale_end / scale_start
    return DepthRange(mind=start.mind * ratio, maxd=start.maxd * ratio)


def range_in_bounds(r: DepthRange, bg_band_top: float) -> bool:
    """True if the range sits on the foreground part of the disparity axis."""
    return r.mind >= bg_band_top and r.maxd <= _MAX_DISPARITY


def sample_start_range(
    rng: random.Random,
    slot: tuple[float, float],
    width: float,
) -> DepthRange:
    """Sample the frame-1 range inside the object's assigned band.

    The band constrains this call and nothing after it. ``width`` is capped at
    the slot width so the range always fits, and a centre is drawn uniformly
    among the positions where it does.
    """
    slot_lo, slot_hi = slot
    half = min(width, slot_hi - slot_lo) / 2.0
    centre = rng.uniform(slot_lo + half, slot_hi - half)
    return DepthRange(mind=centre - half, maxd=centre + half)


def sample_end_pose(
    rng: random.Random,
    cfg: SampleConfig,
    start: DepthRange,
    scale_start: float,
    bg_band_top: float,
    max_tries: int,
) -> tuple[Pose, DepthRange, bool]:
    """Sample an end pose whose derived depth range stays on the disparity axis.

    Rejection sampling. The depth-scale law is applied exactly and any pose
    whose implied range leaves ``[bg_band_top, 1.0]`` is discarded, so the law
    is never bent to fit the axis. A solution always exists because
    ``scale_end == scale_start`` reproduces the start range, which was sampled
    inside the band; ``max_tries`` is therefore a guard, and exhausting it falls
    back to exactly that pose, with its translation redrawn inside the bound the
    forced scale allows.

    Returns the accepted pose, its derived range, and whether the fallback
    fired, so the caller can count fallbacks instead of losing them.
    """
    for _ in range(max_tries):
        pose = sample_fg_pose(rng, cfg)
        end = derive_end_range(start, scale_start, pose.scale)
        if range_in_bounds(end, bg_band_top):
            return pose, end, False
    forced = replace(cfg, scale_min=scale_start, scale_max=scale_start)
    pose = sample_fg_pose(rng, forced)
    return pose, derive_end_range(start, scale_start, scale_start), True
