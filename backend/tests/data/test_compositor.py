from __future__ import annotations

import numpy as np
from PIL import Image

from data._library import write_background, write_foreground
from data.compositor import render_scene, sample_scene
from data.generate_dataset import generate_dataset


def _tiny_library(root) -> None:
    # Two foregrounds: a centred opaque square each, flat depth.
    for fid, val in (("fg_a", 0.6), ("fg_b", 0.9)):
        rgba = np.zeros((32, 32, 4), dtype=np.uint8)
        rgba[8:24, 8:24, :3] = 200
        rgba[8:24, 8:24, 3] = 255
        alpha = (rgba[..., 3] / 255.0).astype(np.float32)
        depth = np.full((32, 32), val, dtype=np.float32)
        write_foreground(root, fid, Image.fromarray(rgba, "RGBA"), alpha, depth)
    write_background(
        root,
        "bg",
        Image.new("RGB", (32, 32), (30, 30, 30)),
        np.full((32, 32), 0.1, dtype=np.float32),
    )


def test_sample_scene_assigns_disjoint_slots(tmp_path) -> None:
    _tiny_library(tmp_path)
    scene = sample_scene(tmp_path, seed=0, n_frames=4, size=32, n_objects=2)
    slots = [obj.slot for obj in scene.objects]
    assert len(slots) == 2
    (lo_a, hi_a), (lo_b, hi_b) = slots
    assert hi_a <= lo_b + 1e-6 or hi_b <= lo_a + 1e-6  # disjoint


def test_render_scene_outputs_aligned_streams(tmp_path) -> None:
    _tiny_library(tmp_path)
    scene = sample_scene(tmp_path, seed=1, n_frames=3, size=32, n_objects=2)
    frames = render_scene(scene)
    assert len(frames) == 3
    f = frames[0]
    assert f.rgb.shape == (32, 32, 3)
    assert f.alpha.shape == (32, 32)
    assert f.disparity.shape == (32, 32)
    # Disparity is in [0, 1]; objects sit above the background band.
    assert 0.0 <= float(f.disparity.min())
    assert float(f.disparity.max()) <= 1.0 + 1e-6
    assert float(f.alpha.max()) > 0.0  # at least one object is visible
    assert float(f.disparity.max()) > scene.bg_band_top  # an object raised depth


def test_oversized_background_leaves_no_black_holes(tmp_path) -> None:
    # One foreground + a solid non-black background stored OVERSIZED (48 > 32
    # frame), mirroring build_library's margin. After pan/zoom/tilt the warped
    # background must still cover the whole frame: no pixel should be pure black.
    rgba = np.zeros((32, 32, 4), dtype=np.uint8)
    rgba[8:24, 8:24, :3] = 200
    rgba[8:24, 8:24, 3] = 255
    write_foreground(
        tmp_path,
        "fg",
        Image.fromarray(rgba, "RGBA"),
        (rgba[..., 3] / 255.0).astype(np.float32),
        np.full((32, 32), 0.6, dtype=np.float32),
    )
    write_background(
        tmp_path,
        "bg",
        Image.new("RGB", (48, 48), (30, 30, 30)),  # oversized, solid gray
        np.full((48, 48), 0.1, dtype=np.float32),
    )
    scene = sample_scene(tmp_path, seed=3, n_frames=6, size=32, n_objects=1)
    for f in render_scene(scene):
        black_holes = (f.rgb.sum(axis=2) == 0).sum()
        assert black_holes == 0, f"{black_holes} black hole pixels from warp"


def test_render_scene_disparity_never_exceeds_one(tmp_path) -> None:
    _tiny_library(tmp_path)
    scene = sample_scene(tmp_path, seed=2, n_frames=5, size=32, n_objects=2)
    for f in render_scene(scene):
        assert float(f.disparity.max()) <= 1.0 + 1e-6


def test_generate_dataset_writes_expected_layout(tmp_path) -> None:
    library = tmp_path / "lib"
    _tiny_library(library)
    out = tmp_path / "synth"
    generate_dataset(
        library_root=library,
        output=out,
        count=2,
        n_frames=3,
        size=32,
        seed=0,
    )
    assert (out / "manifest.csv").exists()
    for sid in ("0001", "0002"):
        seq = out / "sequences" / sid
        assert len(list((seq / "all_in_focus").glob("*.png"))) == 3
        assert len(list((seq / "alpha").glob("*.png"))) == 3
        assert len(list((seq / "disparity").glob("*.png"))) == 3
