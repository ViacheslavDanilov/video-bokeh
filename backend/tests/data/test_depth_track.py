from __future__ import annotations

from data._depth_track import DepthTrack, active_interval, scale_at


def _track(**kw) -> DepthTrack:
    base = {
        "env_lo": 0.20,
        "env_hi": 0.80,
        "active_width": 0.08,
        "z_start": 1.0,
        "z_end": 0.5,
        "z_ref": 1.0,
        "scale_ref": 0.4,
        "disp_ref": 0.5,
    }
    return DepthTrack(**{**base, **kw})


def test_scale_grows_as_z_decreases() -> None:
    t = _track()
    assert scale_at(t, 1.0) > scale_at(t, 0.0)  # closer at end => larger


def test_active_interval_moves_closer_as_z_decreases() -> None:
    t = _track()
    lo0, hi0 = active_interval(t, 0.0)
    lo1, hi1 = active_interval(t, 1.0)
    assert (lo1 + hi1) / 2 > (lo0 + hi0) / 2  # disparity centre rises
    assert abs((hi1 - lo1) - 0.08) < 1e-6


def test_active_interval_clamped_inside_envelope() -> None:
    t = _track(z_end=0.01)  # extreme zoom-in
    lo, hi = active_interval(t, 1.0)
    assert lo >= 0.20 - 1e-6 and hi <= 0.80 + 1e-6
