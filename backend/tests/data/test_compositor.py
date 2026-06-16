from __future__ import annotations

import numpy as np
from PIL import Image

from data._library import write_background, write_foreground
from data.build_library import DEFAULT_BG_MARGIN
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


def test_default_bg_margin_leaves_no_black_holes(tmp_path) -> None:
    # Background stored oversized at the real DEFAULT_BG_MARGIN, solid non-black.
    # Across several motion seeds the warped background must cover the whole frame
    # at every frame: no pixel should be pure black. Guards the margin value.
    size = 128
    src = int(round(size * (1.0 + 2.0 * DEFAULT_BG_MARGIN)))
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[40:88, 40:88, :3] = 200
    rgba[40:88, 40:88, 3] = 255
    write_foreground(
        tmp_path,
        "fg",
        Image.fromarray(rgba, "RGBA"),
        (rgba[..., 3] / 255.0).astype(np.float32),
        np.full((size, size), 0.6, dtype=np.float32),
    )
    write_background(
        tmp_path,
        "bg",
        Image.new("RGB", (src, src), (30, 30, 30)),  # oversized, solid gray
        np.full((src, src), 0.1, dtype=np.float32),
    )
    for seed in range(8):
        scene = sample_scene(tmp_path, seed=seed, n_frames=4, size=size, n_objects=1)
        for f in render_scene(scene):
            holes = int((f.rgb.sum(axis=2) == 0).sum())
            assert holes == 0, f"seed {seed}: {holes} black hole pixels from warp"


def test_render_scene_disparity_never_exceeds_one(tmp_path) -> None:
    _tiny_library(tmp_path)
    scene = sample_scene(tmp_path, seed=2, n_frames=5, size=32, n_objects=2)
    for f in render_scene(scene):
        assert float(f.disparity.max()) <= 1.0 + 1e-6


def test_zoom_in_raises_object_disparity(tmp_path) -> None:
    # Uses a gradient foreground depth so place_in_band exercises real percentile
    # stretch (not the degenerate-band fallback that flat depth triggers).
    from data._library import (
        load_background,
        load_foreground,
        write_background,
        write_foreground,
    )
    from data._sequence_geometry import Pose
    from data.compositor import ObjectTrack, Scene

    size = 32
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[4:28, 4:28, :3] = 180
    rgba[4:28, 4:28, 3] = 255
    # Gradient depth: left=0.1, right=0.9 — large src_range so place_in_band stretches
    depth = np.tile(np.linspace(0.1, 0.9, size, dtype=np.float32), (size, 1))
    alpha = (rgba[..., 3] / 255.0).astype(np.float32)
    write_foreground(tmp_path, "fg_grad", Image.fromarray(rgba, "RGBA"), alpha, depth)
    write_background(
        tmp_path,
        "bg",
        Image.new("RGB", (size, size), (30, 30, 30)),
        np.full((size, size), 0.02, dtype=np.float32),
    )
    fg = load_foreground(tmp_path, "fg_grad")
    bg = load_background(tmp_path, "bg")

    obj = ObjectTrack(
        asset=fg,
        slot=(0.20, 0.80),
        pose_start=Pose(scale=0.3),
        pose_end=Pose(scale=0.75),
        easing="easeInOutSine",
        scale_ref=0.3,
    )
    scene = Scene(
        background=bg,
        objects=[obj],
        bg_pose_start=Pose(scale=1.0),
        bg_pose_end=Pose(scale=1.0),
        bg_easing="easeInOutSine",
        n_frames=2,
        size=size,
    )
    frames = render_scene(scene)
    first = float(frames[0].disparity[frames[0].alpha > 0].mean())
    last = float(frames[-1].disparity[frames[-1].alpha > 0].mean())
    # At scale=0.75 (zoom-in relative to scale_ref=0.3), the active band is
    # shifted toward higher disparity; the mean over object pixels must rise.
    assert last > first + 1e-3
    # Additionally: the max disparity over object pixels must be <= slot_hi + small
    # tolerance, confirming the object is placed inside the active band (not beyond).
    assert float(frames[-1].disparity[frames[-1].alpha > 0].max()) <= 0.80 + 1e-3
    # The object disparity range must be narrow (active_width=0.08), not wide (full
    # slot 0.60); this assertion fails if active_width is not wired into scaled_band.
    obj_disp = frames[-1].disparity[frames[-1].alpha > 0]
    disp_range = float(obj_disp.max() - obj_disp.min())
    assert disp_range < 0.20  # narrower than active_width*(1+margin), not full slot


def test_dynamic_mode_moves_disparity_with_depth(tmp_path) -> None:
    _tiny_library(tmp_path)
    scene = sample_scene(
        tmp_path,
        seed=3,
        n_frames=4,
        size=32,
        n_objects=1,
        depth_mode="dynamic",
    )
    assert scene.objects[0].depth_track is not None
    frames = render_scene(scene)
    first = float(frames[0].disparity[frames[0].alpha > 0].mean())
    last = float(frames[-1].disparity[frames[-1].alpha > 0].mean())
    assert abs(last - first) > 1e-3  # depth actually changes over the clip


def test_fixed_mode_is_unchanged_default(tmp_path) -> None:
    _tiny_library(tmp_path)
    scene = sample_scene(tmp_path, seed=3, n_frames=4, size=32, n_objects=1)
    assert scene.objects[0].depth_track is None


def test_dynamic_scene_is_collision_free(tmp_path) -> None:
    import numpy as np

    from data._collision import pair_collides
    from data._depth_track import active_interval
    from data._sequence_geometry import EASING_FNS, build_fg_homography, warp_pillow

    _tiny_library(tmp_path)
    scene = sample_scene(
        tmp_path,
        seed=28,
        n_frames=4,
        size=32,
        n_objects=2,
        depth_mode="dynamic",
    )
    for i in range(scene.n_frames):
        t = 0.0 if scene.n_frames == 1 else i / (scene.n_frames - 1)
        warped = []
        for obj in scene.objects:
            ease = EASING_FNS[obj.easing](t)
            pose = obj.pose_start.lerp(obj.pose_end, ease)
            h = build_fg_homography(pose, obj.asset.rgb.size[0], scene.size)
            a = np.asarray(warp_pillow(obj.asset.rgb, h, scene.size))[..., 3] / 255.0
            warped.append((a, active_interval(obj.depth_track, ease)))
        for x in range(len(warped)):
            for y in range(x + 1, len(warped)):
                assert not pair_collides(
                    warped[x][0],
                    warped[x][1],
                    warped[y][0],
                    warped[y][1],
                )


def test_dynamic_paint_order_is_frame_local(tmp_path) -> None:
    # Two fully-overlapping opaque squares whose depth order swaps across frames.
    import numpy as np
    from PIL import Image

    from data._depth_track import DepthTrack
    from data._library import (
        load_background,
        load_foreground,
        write_background,
        write_foreground,
    )
    from data._sequence_geometry import Pose
    from data.compositor import ObjectTrack, Scene, render_scene

    def _square(val_rgb):
        rgba = np.zeros((32, 32, 4), dtype=np.uint8)
        rgba[4:28, 4:28, :3] = val_rgb
        rgba[4:28, 4:28, 3] = 255
        return rgba

    a_rgba, b_rgba = _square((200, 0, 0)), _square((0, 0, 200))
    for fid, rgba in (("ra", a_rgba), ("rb", b_rgba)):
        write_foreground(
            tmp_path,
            fid,
            Image.fromarray(rgba, "RGBA"),
            (rgba[..., 3] / 255.0).astype(np.float32),
            np.full((32, 32), 0.5, dtype=np.float32),
        )
    write_background(
        tmp_path,
        "bg",
        Image.new("RGB", (32, 32), (0, 0, 0)),
        np.full((32, 32), 0.1, dtype=np.float32),
    )

    fg_a = load_foreground(tmp_path, "ra")
    fg_b = load_foreground(tmp_path, "rb")
    bg = load_background(tmp_path, "bg")

    # a starts near (high disparity ~0.7) then goes far (disp ~0.3)
    # b starts far (high z) then comes near: disp centre goes from low to high
    # They fully overlap in image space => paint order must swap between frames
    obj_a = ObjectTrack(
        asset=fg_a,
        slot=(0.20, 0.80),
        pose_start=Pose(scale=0.6),
        pose_end=Pose(scale=0.6),
        easing="easeInOutSine",
        scale_ref=0.6,
        depth_track=DepthTrack(0.20, 0.80, 0.08, 0.6, 1.6, 1.0, 0.6, 0.7),
    )
    obj_b = ObjectTrack(
        asset=fg_b,
        slot=(0.20, 0.80),
        pose_start=Pose(scale=0.6),
        pose_end=Pose(scale=0.6),
        easing="easeInOutSine",
        scale_ref=0.6,
        depth_track=DepthTrack(0.20, 0.80, 0.08, 1.6, 0.6, 1.0, 0.6, 0.3),
    )

    scene = Scene(
        background=bg,
        objects=[obj_a, obj_b],
        bg_pose_start=Pose(scale=1.0),
        bg_pose_end=Pose(scale=1.0),
        bg_easing="easeInOutSine",
        n_frames=2,
        size=32,
    )
    frames = render_scene(scene)
    centre0 = frames[0].rgb[16, 16].tolist()
    centre1 = frames[-1].rgb[16, 16].tolist()
    # The nearer (front) colour at the centre must differ between first and last frame,
    # proving paint order is recomputed per frame.
    assert centre0 != centre1


def test_manifest_records_depth_mode_and_rejections(tmp_path) -> None:
    import csv

    library = tmp_path / "lib"
    _tiny_library(library)
    out = tmp_path / "synth"
    generate_dataset(
        library_root=library,
        output=out,
        count=1,
        n_frames=3,
        size=32,
        seed=0,
        depth_mode="dynamic",
    )
    with (out / "manifest.csv").open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    assert "depth_mode" in header
    assert "n_rejections" in header
    data_row = rows[1]
    assert data_row[header.index("depth_mode")] == "dynamic"


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
