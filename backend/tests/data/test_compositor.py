from __future__ import annotations

import csv
import json
import platform
from collections import Counter
from datetime import datetime
from importlib.metadata import version
from statistics import median

import numpy as np
import pytest
from PIL import Image

from video_bokeh.core._library import write_background, write_foreground
from video_bokeh.core._seq_io import sequence_seed
from video_bokeh.core._sequence_geometry import EASING_FNS
from video_bokeh.core._streams import (
    read_alpha_tiff,
    read_disparity_png,
    read_disparity_tiff,
    read_paint_order,
    read_rgb_tiff,
)
from video_bokeh.library.build import DEFAULT_BG_MARGIN
from video_bokeh.scenes._compositor import render_scene, sample_scene
from video_bokeh.scenes.generate import generate_dataset, main, sample_sequence
from video_bokeh.scenes.stats import main as stats_main


def _tiny_library(root, n_fg: int = 2, half: int = 8) -> None:
    # ``n_fg`` foregrounds: a centered opaque square each, flat depth. ``half``
    # shrinks the square, which is what makes crowded scenes placeable at all --
    # five 16x16 objects on a 32x32 frame collide no matter how they are posed.
    for i in range(n_fg):
        val = 0.6 + 0.3 * i / max(n_fg - 1, 1)
        rgba = np.zeros((32, 32, 4), dtype=np.uint8)
        rgba[16 - half : 16 + half, 16 - half : 16 + half, :3] = 200
        rgba[16 - half : 16 + half, 16 - half : 16 + half, 3] = 255
        alpha = (rgba[..., 3] / 255.0).astype(np.float32)
        depth = np.full((32, 32), val, dtype=np.float32)
        write_foreground(root, f"fg_{i}", Image.fromarray(rgba, "RGBA"), alpha, depth)
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
    from video_bokeh.core._library import (
        load_background,
        load_foreground,
        write_background,
        write_foreground,
    )
    from video_bokeh.core._sequence_geometry import Pose
    from video_bokeh.core._trajectory import DepthRange, derive_end_range
    from video_bokeh.scenes._compositor import ObjectTrack, Scene

    size = 32
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[4:28, 4:28, :3] = 180
    rgba[4:28, 4:28, 3] = 255
    # Gradient depth: left=0.1, right=0.9; large src_range so place_in_band stretches
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

    # Scale 0.3 -> 0.75 is a ratio of 2.5, so the derived end range is the start
    # range times 2.5: (0.20, 0.28) becomes (0.50, 0.70), still inside the axis.
    depth_start = DepthRange(mind=0.20, maxd=0.28)
    obj = ObjectTrack(
        asset=fg,
        slot=(0.20, 0.80),
        pose_start=Pose(scale=0.3),
        pose_end=Pose(scale=0.75),
        easing="easeInOutSine",
        depth_start=depth_start,
        depth_end=derive_end_range(depth_start, 0.3, 0.75),
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
    # Growing on screen must move the object nearer, which on the disparity axis
    # means up. This is the claim the whole depth-scale law exists to enforce.
    assert last > first + 1e-3
    # The object stays on the foreground part of the axis.
    assert float(frames[-1].disparity[frames[-1].alpha > 0].max()) <= 1.0
    # Its disparity spread matches the derived end range (0.08 * 2.5 = 0.20), not
    # the full slot: the interval scales with the object, it does not smear.
    obj_disp = frames[-1].disparity[frames[-1].alpha > 0]
    assert float(obj_disp.max() - obj_disp.min()) < 0.25


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
        assert len(list((seq / "alpha").glob("*.tif"))) == 3
        assert len(list((seq / "disparity").glob("*.png"))) == 3
        # the streams are the formats the contract names, not just the right count
        with Image.open(seq / "disparity" / "01.png") as dimg:
            assert dimg.mode == "I;16"


def _overlapping_pair_scene(tmp_path, range_a, range_b, n_frames=2, size=32):
    """Two fully-overlapping opaque squares with hand-picked depth ranges."""
    from video_bokeh.core._library import (
        load_background,
        load_foreground,
        write_background,
        write_foreground,
    )
    from video_bokeh.core._sequence_geometry import Pose
    from video_bokeh.scenes._compositor import ObjectTrack, Scene

    def _square(rgb):
        arr = np.zeros((size, size, 4), dtype=np.uint8)
        arr[4 : size - 4, 4 : size - 4, :3] = rgb
        arr[4 : size - 4, 4 : size - 4, 3] = 255
        return arr

    for fid, rgb in (("ra", (200, 0, 0)), ("rb", (0, 0, 200))):
        arr = _square(rgb)
        write_foreground(
            tmp_path,
            fid,
            Image.fromarray(arr, "RGBA"),
            (arr[..., 3] / 255.0).astype(np.float32),
            np.full((size, size), 0.5, dtype=np.float32),
        )
    write_background(
        tmp_path,
        "bg",
        Image.new("RGB", (size, size), (0, 0, 0)),
        np.full((size, size), 0.1, dtype=np.float32),
    )

    def _track(fid, rng_pair):
        start, end = rng_pair
        return ObjectTrack(
            asset=load_foreground(tmp_path, fid),
            slot=(0.20, 0.80),
            pose_start=Pose(scale=0.6),
            pose_end=Pose(scale=0.6),
            easing="easeInOutSine",
            depth_start=start,
            depth_end=end,
        )

    return Scene(
        background=load_background(tmp_path, "bg"),
        objects=[_track("ra", range_a), _track("rb", range_b)],
        bg_pose_start=Pose(scale=1.0),
        bg_pose_end=Pose(scale=1.0),
        bg_easing="easeInOutSine",
        n_frames=n_frames,
        size=size,
    )


def test_unrestricted_paint_order_is_frame_local(tmp_path) -> None:
    # Goal 6. Object a starts near and ends far; b does the opposite. They fully
    # overlap on screen, so the center pixel color must change between the
    # first and last frame.
    from video_bokeh.core._trajectory import DepthRange

    scene = _overlapping_pair_scene(
        tmp_path,
        range_a=(DepthRange(0.66, 0.74), DepthRange(0.26, 0.34)),
        range_b=(DepthRange(0.26, 0.34), DepthRange(0.66, 0.74)),
    )
    frames = render_scene(scene)
    assert frames[0].rgb[16, 16].tolist() != frames[-1].rgb[16, 16].tolist()


def test_alpha_channels_stay_with_their_object_when_order_swaps(tmp_path) -> None:
    # Goal 11. The spec fixes each object to one alpha channel for the whole
    # clip. Under per-frame paint order that only holds if the alpha list is
    # indexed by object position, not by draw order.
    from dataclasses import replace as dc_replace

    from video_bokeh.core._sequence_geometry import Pose
    from video_bokeh.core._trajectory import DepthRange

    scene = _overlapping_pair_scene(
        tmp_path,
        range_a=(DepthRange(0.66, 0.74), DepthRange(0.26, 0.34)),
        range_b=(DepthRange(0.26, 0.34), DepthRange(0.66, 0.74)),
    )
    # Shrink object b so the two masks differ in area while their depth order
    # still swaps: the areas are what identify which channel holds which object.
    scene.objects[1] = dc_replace(
        scene.objects[1],
        pose_start=Pose(tx=0.25, scale=0.3),
        pose_end=Pose(tx=0.25, scale=0.3),
    )
    frames = render_scene(scene)
    for f in frames:
        assert len(f.object_alphas) == 2
    counts_first = [float((a > 0.5).sum()) for a in frames[0].object_alphas]
    counts_last = [float((a > 0.5).sum()) for a in frames[-1].object_alphas]
    assert counts_first[0] > counts_first[1], "channel 0 is not object 0"
    assert counts_last[0] > counts_last[1], "alpha channels swapped with draw order"


def test_shrunk_range_still_shapes_the_object(tmp_path) -> None:
    # Goal 7. A range that legitimately shrinks under the scale law must still
    # be stretched into, not collapsed onto its midpoint by place_in_band's
    # degenerate guard. The object shrinks on screen from 0.80 to 0.20, so the
    # law moves it away and narrows its range by the same 0.25: start width
    # 0.05 -> end width 0.0125, below the old constant threshold of
    # 0.25 * _ACTIVE_WIDTH = 0.02.
    from video_bokeh.core._library import (
        load_background,
        load_foreground,
        write_background,
        write_foreground,
    )
    from video_bokeh.core._sequence_geometry import Pose
    from video_bokeh.core._trajectory import DepthRange
    from video_bokeh.scenes._compositor import ObjectTrack, Scene

    size = 32
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[4:28, 4:28, :3] = 180
    rgba[4:28, 4:28, 3] = 255
    depth = np.tile(np.linspace(0.1, 0.9, size, dtype=np.float32), (size, 1))
    write_foreground(
        tmp_path,
        "fg_grad",
        Image.fromarray(rgba, "RGBA"),
        (rgba[..., 3] / 255.0).astype(np.float32),
        depth,
    )
    write_background(
        tmp_path,
        "bg",
        Image.new("RGB", (size, size), (30, 30, 30)),
        np.full((size, size), 0.02, dtype=np.float32),
    )
    obj = ObjectTrack(
        asset=load_foreground(tmp_path, "fg_grad"),
        slot=(0.20, 0.80),
        pose_start=Pose(scale=0.80),
        pose_end=Pose(scale=0.20),
        easing="easeInOutSine",
        depth_start=DepthRange(0.50, 0.55),
        depth_end=DepthRange(0.125, 0.1375),
    )
    scene = Scene(
        background=load_background(tmp_path, "bg"),
        objects=[obj],
        bg_pose_start=Pose(scale=1.0),
        bg_pose_end=Pose(scale=1.0),
        bg_easing="easeInOutSine",
        n_frames=2,
        size=size,
    )
    last = render_scene(scene)[-1]
    obj_disp = last.disparity[last.alpha > 0]
    spread = float(obj_disp.max() - obj_disp.min())
    # The end range is 0.0125 wide. A collapsed object would score ~0.
    assert spread > 0.006, f"object collapsed to a depth plate: spread={spread}"


def test_unrestricted_mode_moves_disparity_over_the_clip(tmp_path) -> None:
    _tiny_library(tmp_path)
    scene = sample_scene(
        tmp_path,
        seed=3,
        n_frames=4,
        size=32,
        n_objects=1,
    )
    frames = render_scene(scene)
    first = float(frames[0].disparity[frames[0].alpha > 0].mean())
    last = float(frames[-1].disparity[frames[-1].alpha > 0].mean())
    assert abs(last - first) > 1e-3


def test_unrestricted_depth_moves_with_scale_not_against_it(tmp_path) -> None:
    # Disparity is larger = closer, so an object that grows on screen must end
    # at higher disparity. Inverting the ratio still satisfies every other
    # unrestricted test -- the law holds exactly, ranges stay on the axis,
    # objects leave their slots -- while making the disparity stream contradict
    # the RGB stream in every clip. This is the assertion that pins the sign.
    _tiny_library(tmp_path)
    checked = 0
    for seed in range(40):
        scene = sample_scene(
            tmp_path,
            seed=seed,
            n_frames=4,
            size=32,
            n_objects=2,
        )
        for obj in scene.objects:
            grew = obj.pose_end.scale > obj.pose_start.scale
            came_closer = obj.depth_end.center > obj.depth_start.center
            assert grew == came_closer, (
                f"seed {seed}: scale "
                f"{obj.pose_start.scale:.3f}->{obj.pose_end.scale:.3f} but "
                f"disparity {obj.depth_start.center:.3f}->"
                f"{obj.depth_end.center:.3f}"
            )
            checked += 1
    assert checked == 80


def test_unrestricted_scene_is_collision_free(tmp_path) -> None:
    # Goal 5.
    from video_bokeh.core._collision import pair_collides
    from video_bokeh.core._sequence_geometry import (
        EASING_FNS,
        build_fg_homography,
        warp_pillow,
    )

    _tiny_library(tmp_path)
    scene = sample_scene(
        tmp_path,
        seed=28,
        n_frames=4,
        size=32,
        n_objects=2,
    )
    for i in range(scene.n_frames):
        t = 0.0 if scene.n_frames == 1 else i / (scene.n_frames - 1)
        warped = []
        for obj in scene.objects:
            ease = EASING_FNS[obj.easing](t)
            pose = obj.pose_start.lerp(obj.pose_end, ease)
            h = build_fg_homography(pose, obj.asset.rgb.size[0], scene.size)
            a = np.asarray(warp_pillow(obj.asset.rgb, h, scene.size))[..., 3] / 255.0
            r = obj.depth_start.lerp(obj.depth_end, ease)
            warped.append((a, (r.mind, r.maxd)))
        for x in range(len(warped)):
            for y in range(x + 1, len(warped)):
                assert not pair_collides(
                    warped[x][0],
                    warped[x][1],
                    warped[y][0],
                    warped[y][1],
                )


def test_unrestricted_object_leaves_its_starting_slot(tmp_path) -> None:
    # Goal 4. The whole point of v2: the band constrains frame 1 only. If no
    # seed leaves its slot, the restriction is still in force.
    #
    # Two objects, not one: assign_depth_slots gives a lone object the whole
    # axis (0.05, 1.0), which range_in_bounds already enforces, so a
    # single-object scene can never leave its slot and the assertion would be
    # vacuous. Two objects get (0.05, 0.515) and (0.535, 1.0), which the scale
    # law can cross.
    _tiny_library(tmp_path)
    escaped = False
    for seed in range(60):
        scene = sample_scene(
            tmp_path,
            seed=seed,
            n_frames=8,
            size=32,
            n_objects=2,
        )
        for obj in scene.objects:
            slot_lo, slot_hi = obj.slot
            end = obj.depth_end
            if end.mind < slot_lo - 1e-9 or end.maxd > slot_hi + 1e-9:
                escaped = True
                break
        if escaped:
            break
    assert escaped, "no seed left its starting slot: the band still constrains"


def test_exhausted_retries_raise_instead_of_emitting_a_collision(
    tmp_path,
    monkeypatch,
) -> None:
    # Goal 8. Force the budget to one attempt on a crowded scene of large,
    # fully-opaque objects in adjacent slots, so no sample can be
    # collision-free: the slots are 0.02 apart and the collision margin is
    # also 0.02, which is not strict separation.
    import video_bokeh.scenes._compositor as compositor_module
    from video_bokeh.core._sequence_geometry import SampleConfig

    size = 32
    for fid in ("fg_0", "fg_1"):
        rgba = np.zeros((size, size, 4), dtype=np.uint8)
        rgba[:, :, :3] = 200
        rgba[:, :, 3] = 255  # fully opaque: every placement overlaps
        write_foreground(
            tmp_path,
            fid,
            Image.fromarray(rgba, "RGBA"),
            np.ones((size, size), dtype=np.float32),
            np.full((size, size), 0.5, dtype=np.float32),
        )
    write_background(
        tmp_path,
        "bg",
        Image.new("RGB", (size, size), (30, 30, 30)),
        np.full((size, size), 0.1, dtype=np.float32),
    )
    monkeypatch.setattr(compositor_module, "_MAX_SAMPLE_TRIES", 1)
    cfg = SampleConfig(scale_min=0.79, scale_max=0.80)
    with pytest.raises(compositor_module.CollisionRetriesExhausted, match="collide"):
        sample_scene(
            tmp_path,
            seed=0,
            n_frames=2,
            size=size,
            n_objects=2,
            cfg=cfg,
            bg_band_top=0.90,
        )


def test_manifest_records_the_trajectory_counters(tmp_path) -> None:
    import csv

    library = tmp_path / "lib"
    _tiny_library(library)
    out = tmp_path / "synth"
    written = generate_dataset(
        library_root=library,
        output=out,
        count=1,
        n_frames=3,
        size=32,
        seed=0,
    )
    assert written == 1
    with (out / "manifest.csv").open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header, data_row = rows[0], rows[1]
    for field_name in ("n_rejections", "n_range_fallbacks"):
        assert field_name in header
    assert int(data_row[header.index("n_range_fallbacks")]) >= 0


def test_generate_dataset_skips_a_sequence_it_cannot_sample(
    tmp_path,
    monkeypatch,
) -> None:
    # Goal 8, writer half. A raising sample_scene must cost one sequence, not
    # the whole run, and the surviving sequences keep their seed-derived names.
    import video_bokeh.scenes.generate as writer_module
    from video_bokeh.scenes._compositor import CollisionRetriesExhausted

    library = tmp_path / "lib"
    _tiny_library(library)
    out = tmp_path / "synth"
    real_sample_scene = writer_module.sample_scene

    def _fail_on_second(*args, **kwargs):
        if kwargs["seed"] == 1:
            raise CollisionRetriesExhausted("seed 1: forced")
        return real_sample_scene(*args, **kwargs)

    monkeypatch.setattr(writer_module, "sample_scene", _fail_on_second)
    written = generate_dataset(
        library_root=library,
        output=out,
        count=3,
        n_frames=2,
        size=32,
        seed=0,
    )
    assert written == 2
    assert (out / "sequences" / "0001").is_dir()
    assert not (out / "sequences" / "0002").exists()  # the skipped seed's slot
    assert (out / "sequences" / "0003").is_dir()


def test_generate_dataset_writes_a_page_per_object_past_three(tmp_path) -> None:
    # The three-object ceiling was the RGB PNG's, not the pipeline's. With a
    # multi-page TIFF the count is bounded only by what the depth axis can place.
    library = tmp_path / "lib"
    _tiny_library(library, n_fg=5, half=3)
    out = tmp_path / "synth"
    written = generate_dataset(
        library_root=library,
        output=out,
        count=1,
        n_frames=2,
        size=32,
        seed=0,
        n_objects_min=5,
        n_objects_max=5,
    )
    assert written == 1

    frame = out / "sequences" / "0001" / "alpha" / "01.tif"
    assert len(read_alpha_tiff(frame)) == 5


def _composite_layers(frame) -> tuple[np.ndarray, np.ndarray]:
    """Painter's compositing of a frame's layers, in the paint order it records."""
    layers = frame.layers
    rgb = layers.background_rgb
    disparity = layers.background_disparity
    for idx in layers.paint_order:
        a = frame.object_alphas[idx]
        rgb = a[..., None] * layers.object_rgbs[idx] + (1.0 - a[..., None]) * rgb
        disparity = a * layers.object_disparities[idx] + (1.0 - a) * disparity
    return rgb, np.clip(disparity, 0.0, 1.0)


def test_layers_composited_in_paint_order_give_back_the_frame(tmp_path) -> None:
    # The two squares overlap fully and swap depth over the clip, so a wrong paint
    # order, or an object layer that is not the whole object, shows in the color.
    from video_bokeh.core._trajectory import DepthRange

    scene = _overlapping_pair_scene(
        tmp_path,
        range_a=(DepthRange(0.66, 0.74), DepthRange(0.26, 0.34)),
        range_b=(DepthRange(0.26, 0.34), DepthRange(0.66, 0.74)),
    )
    frames = render_scene(scene, layers=True)
    assert frames[0].layers.paint_order != frames[-1].layers.paint_order
    for frame in frames:
        rgb, disparity = _composite_layers(frame)
        np.testing.assert_array_equal(rgb, frame.rgb)
        np.testing.assert_array_equal(disparity, frame.disparity)


def test_an_object_layer_is_zero_outside_its_alpha_mask(tmp_path) -> None:
    _tiny_library(tmp_path)
    scene = sample_scene(tmp_path, seed=1, n_frames=3, size=32, n_objects=2)
    for frame in render_scene(scene, layers=True):
        for idx, a in enumerate(frame.object_alphas):
            outside = a == 0
            assert outside.any() and (~outside).any()
            assert not frame.layers.object_rgbs[idx][outside].any()
            assert not frame.layers.object_disparities[idx][outside].any()
            assert frame.layers.object_disparities[idx][~outside].min() > 0


def test_keeping_the_layers_leaves_the_frame_unchanged(tmp_path) -> None:
    _tiny_library(tmp_path)
    scene = sample_scene(tmp_path, seed=1, n_frames=3, size=32, n_objects=2)
    plain = render_scene(scene)
    layered = render_scene(scene, layers=True)
    for a, b in zip(plain, layered, strict=True):
        assert a.layers is None
        np.testing.assert_array_equal(a.rgb, b.rgb)
        np.testing.assert_array_equal(a.alpha, b.alpha)
        np.testing.assert_array_equal(a.disparity, b.disparity)
        np.testing.assert_array_equal(
            np.stack(a.object_alphas),
            np.stack(b.object_alphas),
        )


def _read_png(path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im, dtype=np.float32)


def test_written_layers_give_back_the_written_frame(tmp_path) -> None:
    library = tmp_path / "lib"
    _tiny_library(library)
    out = tmp_path / "synth"
    main(
        [
            "--library-root",
            str(library),
            "--output",
            str(out),
            "--count",
            "2",
            "--frames",
            "3",
            "--size",
            "32",
            "--n-objects-max",
            "2",
            "--layers",
        ],
    )
    for seq in sorted((out / "sequences").iterdir()):
        layers = seq / "layers"
        order = read_paint_order(layers / "paint_order.json")
        assert len(order) == 3
        for stem, frame_order in zip(("01", "02", "03"), order, strict=True):
            alphas = read_alpha_tiff(seq / "alpha" / f"{stem}.tif")
            colors = read_rgb_tiff(layers / "objects" / f"{stem}.tif")
            disparities = read_disparity_tiff(
                layers / "objects_disparity" / f"{stem}.tif",
            )
            assert len(colors) == len(disparities) == len(alphas)
            assert sorted(frame_order) == list(range(len(alphas)))
            for k, a in enumerate(alphas):
                assert not colors[k][a == 0].any()
                assert not disparities[k][a == 0].any()

            rgb = _read_png(layers / "background" / f"{stem}.png")
            disparity = read_disparity_png(
                layers / "background_disparity" / f"{stem}.png",
            )
            for k in frame_order:
                a = alphas[k]
                rgb = a[..., None] * colors[k] + (1.0 - a[..., None]) * rgb
                disparity = a * disparities[k] + (1.0 - a) * disparity

            aif = _read_png(seq / "all_in_focus" / f"{stem}.png")
            uncovered = np.stack(alphas).max(axis=0) == 0
            assert uncovered.any()
            np.testing.assert_array_equal(rgb[uncovered], aif[uncovered])
            # The frame and each layer are truncated to 8 bits on their own: under one
            # and a half levels apart, measured under one.
            assert np.abs(rgb - aif).max() < 1.5
            written = read_disparity_png(seq / "disparity" / f"{stem}.png")
            # The fixture's alpha comes from 8-bit images, so the stored alpha is exact.
            # Each disparity map is off by half a 16-bit step at most, so the two sides
            # differ by one step.
            assert np.abs(disparity - written).max() <= 1 / 65535 + 1e-6


def test_no_layers_are_written_unless_asked(tmp_path) -> None:
    library = tmp_path / "lib"
    _tiny_library(library)
    out = tmp_path / "synth"
    generate_dataset(library, out, count=1, n_frames=2, size=32, seed=0)
    assert not (out / "sequences" / "0001" / "layers").exists()


def test_rewriting_a_sequence_drops_its_old_layers(tmp_path) -> None:
    # paint_order.json marks a complete layers/, so layers left from an earlier run
    # would pass for this run's.
    library = tmp_path / "lib"
    _tiny_library(library)
    out = tmp_path / "synth"
    generate_dataset(library, out, count=1, n_frames=2, size=32, seed=0, layers=True)
    assert (out / "sequences" / "0001" / "layers" / "paint_order.json").is_file()
    generate_dataset(library, out, count=1, n_frames=2, size=32, seed=5)
    assert not (out / "sequences" / "0001" / "layers").exists()


@pytest.mark.parametrize("n_frames,fallback", [(3, False), (1, False), (3, True)])
def test_scene_records_match_the_sampled_scene(
    tmp_path, monkeypatch, n_frames, fallback
):
    import video_bokeh.scenes._compositor as compositor

    library = tmp_path / "lib"
    _tiny_library(library)
    # Exhaust the range budget to exercise the real sampler's fallback path.
    if fallback:
        monkeypatch.setattr(compositor, "_MAX_RANGE_TRIES", 0)
    (library / "foregrounds/fg_1/meta.json").write_text(
        '{"estimator": "test-estimator"}', encoding="utf-8"
    )
    out = tmp_path / "synth"
    argv = [
        "--library-root",
        str(library),
        "--output",
        str(out),
        "--count",
        "2",
        "--frames",
        str(n_frames),
        "--size",
        "32",
        "--seed",
        "0",
        "--n-objects-min",
        "2",
        "--n-objects-max",
        "2",
        "--layers",
        "--flow",
    ]
    assert main(argv) == 0
    with (out / "manifest.csv").open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == [
            "seq_id",
            "seed",
            "n_frames",
            "size",
            "n_objects",
            "n_rejections",
            "n_range_fallbacks",
            "background",
        ]
        manifest = list(reader)
    with (out / "objects.csv").open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == [
            "seq_id",
            "object",
            "foreground",
            "easing",
            "scale_start",
            "scale_end",
            "band_lo_first",
            "band_hi_first",
            "band_lo_last",
            "band_hi_last",
            "depth_motion",
            "range_fallback",
        ]
        objects = list(reader)
    assert [(r["seq_id"], int(r["object"])) for r in objects] == [
        (sid, index) for sid in ("0001", "0002") for index in range(2)
    ]
    for seed, row in enumerate(manifest):
        scene = sample_sequence(library, seed, n_frames, 32, 2, 2)
        seq = out / "sequences" / row["seq_id"]
        assert sequence_seed(seq) == seed  # The existing manifest reader.
        assert row["background"] == scene.background.asset_id
        assert int(row["n_objects"]) == len(scene.objects)
        assert int(row["n_rejections"]) == scene.n_rejections
        assert int(row["n_frames"]) == len(list((seq / "all_in_focus").glob("*.png")))
        assert int(row["size"]) == 32
        assert int(row["n_range_fallbacks"]) == sum(
            o.range_fallback for o in scene.objects
        )
        assert scene.n_range_fallbacks == (2 if fallback else 0)
        records = [o for o in objects if o["seq_id"] == row["seq_id"]]
        assert len(read_alpha_tiff(seq / "alpha/01.tif")) == len(records)
        for obj, record in zip(scene.objects, records, strict=True):
            assert record["foreground"] == obj.asset.asset_id
            assert record["easing"] == obj.easing
            assert float(record["scale_start"]) == obj.pose_start.scale
            assert float(record["scale_end"]) == obj.pose_end.scale
            bands = []
            for label, t in (("first", 0.0), ("last", 0.0 if n_frames == 1 else 1.0)):
                band = obj.depth_start.lerp(obj.depth_end, EASING_FNS[obj.easing](t))
                assert float(record[f"band_lo_{label}"]) == band.mind
                assert float(record[f"band_hi_{label}"]) == band.maxd
                bands.append(band)
            assert record["depth_motion"] == str(bands[0] != bands[1]).lower()
            assert record["range_fallback"] == str(fallback).lower()
    run = json.loads((out / "run.json").read_text())
    assert run["flags"] == {
        "library_root": str(library),
        "output": str(out),
        "count": 2,
        "frames": n_frames,
        "size": 32,
        "seed": 0,
        "n_objects_min": 2,
        "n_objects_max": 2,
        "layers": True,
        "flow": True,
        "flow_back": False,
        "occlusion": False,
        "bokeh": False,
        "bokeh_strength": 16.0,
        "split": "train",
    }
    assert run["library_root"] == str(library.resolve())
    assert run["estimator"] == "test-estimator"
    assert "git_commit" not in run
    assert datetime.fromisoformat(run["date"]).utcoffset().total_seconds() == 0
    assert run["versions"] == {
        "python": platform.python_version(),
        "numpy": version("numpy"),
        "Pillow": version("Pillow"),
    }
    assert run["bokeh_device"] is None
    assert run["sequences_requested"] == run["sequences_written"] == 2
    assert run["skipped_seeds"] == []
    assert run["wall_seconds"] > 0


@pytest.mark.parametrize("record", ["objects.csv", "run.json"])
@pytest.mark.parametrize("rerun", [False, True])
def test_record_write_failure_leaves_no_manifest(tmp_path, record, rerun):
    library = tmp_path / "lib"
    _tiny_library(library)
    out = tmp_path / "synth"
    if rerun:
        generate_dataset(library, out, 1, 1, 32, 0)
        assert (out / "manifest.csv").is_file()
        (out / record).unlink()
    # A directory at a record's path forces a real filesystem write failure.
    (out / record).mkdir(parents=True)
    with pytest.raises(IsADirectoryError):
        main(
            [
                "--library-root",
                str(library),
                "--output",
                str(out),
                "--count",
                "1",
                "--frames",
                "1",
                "--size",
                "32",
                "--n-objects-max",
                "1",
            ]
        )
    assert (out / "sequences/0001/all_in_focus/01.png").is_file()
    assert not (out / "manifest.csv").exists()


def test_manifest_write_failure_leaves_no_completion_marker(
    tmp_path, monkeypatch, capsys
):
    library = tmp_path / "lib"
    _tiny_library(library)
    out = tmp_path / "synth"
    argv = [
        "--library-root",
        str(library),
        "--output",
        str(out),
        "--count",
        "2",
        "--frames",
        "1",
        "--size",
        "32",
        "--n-objects-max",
        "1",
    ]
    assert main(argv) == 0
    assert (out / "manifest.csv").is_file()
    settings = "count=2 frames=1 size=32\n"
    (out / ".lab-settings").write_text(settings, encoding="utf-8")
    csv_writer = csv.writer

    class FailingManifestWriter:
        def __init__(self, *args, **kwargs):
            self.writer = csv_writer(*args, **kwargs)
            self.manifest = False

        def writerow(self, row):
            self.manifest = tuple(row[:2]) == ("seq_id", "seed")
            return self.writer.writerow(row)

        def writerows(self, rows):
            if self.manifest:
                self.writer.writerow(next(iter(rows)))
                raise OSError("manifest write failed midway")
            return self.writer.writerows(rows)

    monkeypatch.setattr(csv, "writer", FailingManifestWriter)
    with pytest.raises(OSError, match="manifest write failed midway"):
        main(argv)
    assert not (out / "manifest.csv").exists()
    assert (out / ".lab-settings").read_text(encoding="utf-8") == settings
    with (out / "manifest.csv.tmp").open(encoding="utf-8", newline="") as f:
        assert len(list(csv.DictReader(f))) == 1
    with pytest.raises(SystemExit) as exc:
        stats_main(["--data-root", str(out)])
    assert exc.value.code == 2
    assert f"missing required dataset record: {out / 'manifest.csv'}" in (
        capsys.readouterr().err
    )


def test_stats_command_has_hand_calculated_totals(tmp_path, capsys):
    (tmp_path / "manifest.csv").write_text(
        "seq_id,seed,n_frames,size,n_objects,n_rejections,n_range_fallbacks,background\n"
        "0001,0,2,32,1,3,1,bg_a\n"
        "0002,1,1,32,2,0,0,bg_a\n"
        "0003,2,1,32,0,3,0,bg_b\n",
        encoding="utf-8",
    )
    (tmp_path / "objects.csv").write_text(
        "seq_id,object,foreground,easing,scale_start,scale_end,band_lo_first,"
        "band_hi_first,band_lo_last,band_hi_last,depth_motion,range_fallback\n"
        "0001,0,fg_a,linear,1,1,0.125,0.25,0.25,0.375,true,true\n"
        "0002,0,fg_a,linear,1,1,0.25,0.5,0.25,0.5,false,false\n"
        "0002,1,fg_b,linear,1,1,0.5,1,0.25,0.75,true,false\n",
        encoding="utf-8",
    )
    (tmp_path / "run.json").write_text('{"seed":7}', encoding="utf-8")
    # Four frames; nested layer files and bokeh metadata count toward byte totals.
    for name, contents in {
        "0001/all_in_focus/01.png": b"a",
        "0001/all_in_focus/02.png": b"abc",
        "0002/all_in_focus/01.png": b"ab",
        "0003/all_in_focus/01.png": b"ab",
        "0001/alpha/01.tif": b"ab",
        "0002/alpha/01.tif": b"a",
        "0003/alpha/01.tif": b"a",
        "0001/disparity/01.png": b"abcdef",
        "0002/disparity/01.png": b"abc",
        "0003/disparity/01.png": b"abc",
        "0001/layers/objects/01.tif": b"abcdef",
        "0001/layers/paint_order.json": b"[]",
        "0001/flow/01.png": b"ab",
        "0001/bokeh/01.png": b"ab",
        "0001/bokeh/focus.json": b'{"object":0}',
        "0002/bokeh/01.png": b"abc",  # No focus.json.
        "0003/bokeh/focus.json": b'{"object":null}',  # Zero objects.
        "9999/all_in_focus/stale.png": b"ignored",
    }.items():
        path = tmp_path / "sequences" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    assert stats_main(["--data-root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "sequences": 3,
        "frames": 4,
        "objects_per_sequence": {"counts": {"0": 1, "1": 1, "2": 1}, "mean": 1.0},
        "depth_motion_share": 2 / 3,
        "range_fallback_share": 1 / 3,
        "rejections": {"total": 6, "mean_per_sequence": 2.0},
        "foreground_reuse": {"distinct": 2, "max_uses": 2},
        "background_reuse": {"distinct": 2, "max_uses": 2},
        "active_band_width_first": {"min": 0.125, "median": 0.25, "max": 0.5},
        "object_focus_share": 1 / 3,
        "bytes_per_stream": {
            "all_in_focus": {"total": 8, "per_frame": 2.0},
            "alpha": {"total": 4, "per_frame": 1.0},
            "disparity": {"total": 12, "per_frame": 3.0},
            "layers": {"total": 8, "per_frame": 2.0},
            "flow": {"total": 2, "per_frame": 0.5},
            "flow_back": {"total": 0, "per_frame": 0.0},
            "occlusion": {"total": 0, "per_frame": 0.0},
            "bokeh": {"total": 32, "per_frame": 8.0},
        },
        "run": {"seed": 7},
    }


@pytest.mark.parametrize("bokeh", [False, True])
def test_stats_command_counts_records_focus_and_files(
    tmp_path, monkeypatch, capsys, bokeh
):
    if bokeh:
        pytest.importorskip("torch")
        monkeypatch.setenv("VIDEO_BOKEH_LAYERED_DEVICE", "cpu")
    library = tmp_path / "lib"
    _tiny_library(library)
    out = tmp_path / "synth"
    generate_dataset(
        library, out, 2, 2, 32, 0, layers=True, flow=True, bokeh=bokeh, bokeh_strength=0
    )
    scenes = [sample_sequence(library, seed, 2, 32, 1, 5) for seed in range(2)]
    if bokeh:
        # Object page 0 must count as focused; null must not.
        for sid, obj in (("0001", 0), ("0002", None)):
            path = out / "sequences" / sid / "bokeh/focus.json"
            focus = json.loads(path.read_text())
            focus["object"] = obj
            path.write_text(json.dumps(focus), encoding="utf-8")
    # A stale sequence outside the rewritten manifest must not count.
    stale = out / "sequences/9999/all_in_focus"
    stale.mkdir(parents=True)
    (stale / "stale.png").write_bytes(b"stale")
    capsys.readouterr()
    output = tmp_path / "stats.json"
    assert stats_main(["--data-root", str(out), "--output", str(output)]) == 0
    printed = capsys.readouterr().out
    assert printed == output.read_text()
    stats = json.loads(printed)
    objects = [obj for scene in scenes for obj in scene.objects]
    counts = Counter(len(scene.objects) for scene in scenes)
    widths = [obj.depth_start.width for obj in objects]
    assert stats["sequences"] == 2
    assert stats["frames"] == 4
    assert stats["objects_per_sequence"] == {
        "counts": {str(k): v for k, v in counts.items()},
        "mean": len(objects) / 2,
    }
    assert stats["depth_motion_share"] == sum(
        obj.depth_start != obj.depth_end for obj in objects
    ) / len(objects)
    assert stats["range_fallback_share"] == sum(
        o.range_fallback for o in objects
    ) / len(objects)
    assert stats["rejections"] == {
        "total": sum(s.n_rejections for s in scenes),
        "mean_per_sequence": sum(s.n_rejections for s in scenes) / 2,
    }
    for key, ids in (
        ("foreground_reuse", [o.asset.asset_id for o in objects]),
        ("background_reuse", [s.background.asset_id for s in scenes]),
    ):
        assert stats[key] == {
            "distinct": len(set(ids)),
            "max_uses": max(Counter(ids).values()),
        }
    assert stats["active_band_width_first"] == {
        "min": min(widths),
        "median": median(widths),
        "max": max(widths),
    }
    assert stats["object_focus_share"] == (0.5 if bokeh else None)
    for stream, sizes in stats["bytes_per_stream"].items():
        total = sum(
            p.stat().st_size
            for sid in ("0001", "0002")
            for p in (out / "sequences" / sid / stream).rglob("*")
            if p.is_file()
        )
        assert sizes == {"total": total, "per_frame": total / 4}
    assert stats["run"] == json.loads((out / "run.json").read_text())
    assert stats["run"]["estimator"] is None
    if bokeh:
        assert stats["run"]["bokeh_device"] == "cpu"
        assert stats["run"]["versions"]["torch"] == version("torch")


@pytest.mark.parametrize("missing", ["objects.csv", "run.json"])
def test_stats_names_missing_record(tmp_path, capsys, missing):
    for name in ("manifest.csv", "objects.csv", "run.json"):
        if name != missing:
            (tmp_path / name).touch()
    with pytest.raises(SystemExit) as exc:
        stats_main(["--data-root", str(tmp_path)])
    assert exc.value.code == 2
    assert (
        f"missing required dataset record: {tmp_path / missing}"
        in capsys.readouterr().err
    )


def test_records_are_rewritten_and_include_skipped_seeds(tmp_path, monkeypatch):
    import video_bokeh.scenes.generate as writer
    from video_bokeh.scenes._compositor import CollisionRetriesExhausted

    library = tmp_path / "lib"
    _tiny_library(library)
    out = tmp_path / "synth"
    generate_dataset(library, out, 2, 2, 32, 0)

    def reject(*args, **kwargs):
        raise CollisionRetriesExhausted("forced rejection")

    monkeypatch.setattr(writer, "sample_sequence", reject)
    assert generate_dataset(library, out, 1, 2, 32, 7) == 0
    for name in ("manifest.csv", "objects.csv"):
        with (out / name).open(encoding="utf-8") as f:
            assert list(csv.DictReader(f)) == []
    run = json.loads((out / "run.json").read_text())
    assert run["sequences_requested"] == 1
    assert run["sequences_written"] == 0
    assert run["skipped_seeds"] == [7]
    assert stats_main(["--data-root", str(out)]) == 0
