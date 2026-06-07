from __future__ import annotations

import random

import numpy as np
from PIL import Image

from data._sequence_geometry import (
    Pose,
    SampleConfig,
    build_bg_homography,
    build_fg_homography,
    resize_shortest_side_and_center_crop,
    sample_fg_pose,
    warp_depth,
    warp_pillow,
)


def test_pose_lerp_midpoint() -> None:
    a = Pose(tx=0.0, ty=0.0, scale=0.2)
    b = Pose(tx=1.0, ty=1.0, scale=0.8)
    mid = a.lerp(b, 0.5)
    assert mid.tx == 0.5
    assert mid.ty == 0.5
    assert abs(mid.scale - 0.5) < 1e-6


def test_fg_homography_is_3x3() -> None:
    h = build_fg_homography(Pose(scale=0.5), src_size=64, frame_size=128)
    assert h.shape == (3, 3)


def test_bg_homography_is_3x3() -> None:
    h = build_bg_homography(Pose(scale=1.0), src_size=160, frame_size=128)
    assert h.shape == (3, 3)


def test_warp_pillow_keeps_size_and_mode() -> None:
    img = Image.new("RGBA", (64, 64), (10, 20, 30, 255))
    h = build_fg_homography(Pose(scale=0.5), src_size=64, frame_size=64)
    out = warp_pillow(img, h, out_size=64)
    assert out.size == (64, 64)
    assert out.mode == "RGBA"


def test_warp_depth_preserves_dtype_and_size() -> None:
    depth = np.linspace(0, 1, 64 * 64, dtype=np.float32).reshape(64, 64)
    h = build_fg_homography(Pose(scale=0.5), src_size=64, frame_size=64)
    out = warp_depth(depth, h, out_size=64)
    assert out.shape == (64, 64)
    assert out.dtype == np.float32
    assert 0.0 <= float(out.max()) <= 1.0 + 1e-6


def test_warp_depth_identity_is_noop() -> None:
    depth = np.random.default_rng(0).random((32, 32)).astype(np.float32)
    h = build_fg_homography(
        Pose(tx=0.0, ty=0.0, scale=1.0),
        src_size=32,
        frame_size=32,
    )
    out = warp_depth(depth, h, out_size=32)
    assert out.shape == (32, 32)


def test_sample_fg_pose_is_deterministic_for_same_seed() -> None:
    cfg = SampleConfig()
    first = sample_fg_pose(random.Random(7), cfg)
    second = sample_fg_pose(random.Random(7), cfg)
    assert first == second


def test_resize_shortest_side_and_center_crop_is_square() -> None:
    img = Image.new("RGB", (200, 100), (0, 0, 0))
    out = resize_shortest_side_and_center_crop(img, 64)
    assert out.size == (64, 64)
