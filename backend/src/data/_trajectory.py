"""Unrestricted depth trajectories: a per-object disparity range over time.

An object's depth state at a frame is the interval [mind, maxd] its warped depth
map is remapped into. The interval at the end of the clip is derived from the
start interval and the scale ratio, never sampled: growing on screen by a factor
k must bring the object k times closer. The assigned depth band constrains only
the start interval; every later frame is free.

See docs/superpowers/specs/2026-09-09-unrestricted-trajectories-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    """
    if scale_end <= 1e-8:
        raise ValueError(f"scale_end must be positive, got {scale_end}")
    ratio = scale_start / scale_end
    return DepthRange(mind=start.mind * ratio, maxd=start.maxd * ratio)


def range_in_bounds(r: DepthRange, bg_band_top: float) -> bool:
    """True if the range sits on the foreground part of the disparity axis."""
    return r.mind >= bg_band_top and r.maxd <= _MAX_DISPARITY
