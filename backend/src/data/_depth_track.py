"""Camera-space depth track: one z(t) per object drives scale and disparity.

A single magnification factor m(t) = z_ref / z(t) feeds both apparent scale and
disparity centre, so an object that grows on screen also moves closer in depth.
This is a flat cardboard-layer model: z is a synthetic per-object reference, not
a metric measurement.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DepthTrack:
    env_lo: float  # envelope lower disparity bound
    env_hi: float  # envelope upper disparity bound
    active_width: float  # thickness of the occupied interval, in disparity
    z_start: float  # camera-space depth at t=0 (larger = farther)
    z_end: float  # camera-space depth at t=1
    z_ref: float  # reference depth at which scale == scale_ref
    scale_ref: float  # Pose.scale at z_ref
    disp_ref: float  # disparity centre at z_ref (envelope centre by default)


def _z_at(track: DepthTrack, t: float) -> float:
    return track.z_start + (track.z_end - track.z_start) * t


def _mag(track: DepthTrack, t: float) -> float:
    z = _z_at(track, t)
    return track.z_ref / z if z > 1e-8 else 1.0


def scale_at(track: DepthTrack, t: float) -> float:
    """Apparent scale derived from depth: scale_ref * z_ref / z(t)."""
    return track.scale_ref * _mag(track, t)


def active_interval(track: DepthTrack, t: float) -> tuple[float, float]:
    """Occupied disparity interval at eased time ``t``, clamped to the envelope."""
    width = min(track.active_width, track.env_hi - track.env_lo)
    centre = track.disp_ref * _mag(track, t)
    half = width / 2.0
    centre = min(max(centre, track.env_lo + half), track.env_hi - half)
    return centre - half, centre + half
