from __future__ import annotations

import pytest

from data._trajectory import DepthRange, derive_end_range, range_in_bounds


def test_depth_range_width_and_centre() -> None:
    r = DepthRange(0.20, 0.28)
    assert r.width == pytest.approx(0.08)
    assert r.centre == pytest.approx(0.24)


def test_lerp_moves_both_bounds_together() -> None:
    a = DepthRange(0.20, 0.28)
    b = DepthRange(0.40, 0.56)
    mid = a.lerp(b, 0.5)
    assert mid.mind == pytest.approx(0.30)
    assert mid.maxd == pytest.approx(0.42)


def test_lerp_endpoints_are_exact() -> None:
    a = DepthRange(0.20, 0.28)
    b = DepthRange(0.40, 0.56)
    assert a.lerp(b, 0.0) == a
    assert a.lerp(b, 1.0) == b


def test_derive_end_range_obeys_the_scale_ratio_exactly() -> None:
    # Goal 1: growing on screen by k must divide the depth range by k.
    start = DepthRange(0.30, 0.38)
    end = derive_end_range(start, scale_start=0.25, scale_end=0.50)
    assert end.mind / start.mind == pytest.approx(0.5, abs=1e-9)
    assert end.maxd / start.maxd == pytest.approx(0.5, abs=1e-9)


def test_derive_end_range_grows_the_range_when_the_object_shrinks() -> None:
    start = DepthRange(0.10, 0.18)
    end = derive_end_range(start, scale_start=0.80, scale_end=0.20)
    assert end.mind == pytest.approx(0.40)
    assert end.maxd == pytest.approx(0.72)


def test_derive_end_range_is_identity_at_equal_scales() -> None:
    # This is what makes the rejection loop in Task 3 always terminate.
    start = DepthRange(0.31, 0.39)
    assert derive_end_range(start, 0.4, 0.4) == start


def test_derive_end_range_rejects_a_non_positive_scale() -> None:
    with pytest.raises(ValueError, match="scale_end must be positive"):
        derive_end_range(DepthRange(0.1, 0.2), scale_start=0.5, scale_end=0.0)


def test_range_in_bounds_accepts_the_slot_boundary() -> None:
    # assign_depth_slots gives the first slot lo == bg_band_top, so touching
    # the boundary is a configuration the slot layout produces by construction.
    assert range_in_bounds(DepthRange(0.05, 0.50), bg_band_top=0.05)
    assert range_in_bounds(DepthRange(0.10, 1.00), bg_band_top=0.05)


def test_range_in_bounds_rejects_a_range_that_leaves_the_axis() -> None:
    assert not range_in_bounds(DepthRange(0.10, 1.40), bg_band_top=0.05)
    assert not range_in_bounds(DepthRange(0.04, 0.50), bg_band_top=0.05)
