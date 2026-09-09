from __future__ import annotations

import random

import pytest

from data._sequence_geometry import SampleConfig
from data._trajectory import (
    DepthRange,
    derive_end_range,
    range_in_bounds,
    sample_end_pose,
    sample_start_range,
)


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


def test_sample_start_range_lands_inside_the_slot() -> None:
    for seed in range(200):
        r = sample_start_range(random.Random(seed), (0.30, 0.60), width=0.08)
        assert r.mind >= 0.30 - 1e-12
        assert r.maxd <= 0.60 + 1e-12
        assert r.width == pytest.approx(0.08)


def test_sample_start_range_caps_width_at_the_slot_width() -> None:
    r = sample_start_range(random.Random(0), (0.30, 0.34), width=0.08)
    assert r.width == pytest.approx(0.04)
    assert r.mind == pytest.approx(0.30)
    assert r.maxd == pytest.approx(0.34)


def test_sample_end_pose_always_returns_an_in_bounds_range() -> None:
    # Goal 2: 200 seeds, no range leaves the axis.
    cfg = SampleConfig()
    for seed in range(200):
        rng = random.Random(seed)
        start = sample_start_range(rng, (0.05, 0.35), width=0.08)
        pose, end, _ = sample_end_pose(
            rng,
            cfg,
            start,
            scale_start=0.5,
            bg_band_top=0.05,
            max_tries=100,
        )
        assert range_in_bounds(end, 0.05), f"seed {seed}: {end}"
        assert cfg.scale_min <= pose.scale <= cfg.scale_max


def test_sample_end_pose_obeys_the_law_for_the_pose_it_returns() -> None:
    cfg = SampleConfig()
    rng = random.Random(11)
    start = sample_start_range(rng, (0.10, 0.40), width=0.08)
    pose, end, _ = sample_end_pose(
        rng,
        cfg,
        start,
        scale_start=0.5,
        bg_band_top=0.05,
        max_tries=100,
    )
    assert end == derive_end_range(start, 0.5, pose.scale)


def test_sample_end_pose_falls_back_to_the_start_scale_when_retries_run_out() -> None:
    cfg = SampleConfig()
    rng = random.Random(3)
    start = sample_start_range(rng, (0.10, 0.40), width=0.08)
    pose, end, used_fallback = sample_end_pose(
        rng,
        cfg,
        start,
        scale_start=0.5,
        bg_band_top=0.05,
        max_tries=0,
    )
    assert used_fallback is True
    assert pose.scale == pytest.approx(0.5)
    assert end == start  # ratio 1.0 reproduces the start range
    assert range_in_bounds(end, 0.05)
