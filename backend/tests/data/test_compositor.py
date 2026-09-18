from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from data._library import write_background, write_foreground
from data._streams import read_alpha_tiff, read_disparity_png
from data.build_library import DEFAULT_BG_MARGIN
from data.compositor import render_scene, sample_scene
from data.generate_dataset import generate_dataset


def _tiny_library(root, n_fg: int = 2, half: int = 8) -> None:
    # ``n_fg`` foregrounds: a centred opaque square each, flat depth. ``half``
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
    from data._library import (
        load_background,
        load_foreground,
        write_background,
        write_foreground,
    )
    from data._sequence_geometry import Pose
    from data._trajectory import DepthRange, derive_end_range
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
    from data._library import (
        load_background,
        load_foreground,
        write_background,
        write_foreground,
    )
    from data._sequence_geometry import Pose
    from data.compositor import ObjectTrack, Scene

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
    # overlap on screen, so the centre pixel colour must change between the
    # first and last frame.
    from data._trajectory import DepthRange

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

    from data._sequence_geometry import Pose
    from data._trajectory import DepthRange

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
    from data._library import (
        load_background,
        load_foreground,
        write_background,
        write_foreground,
    )
    from data._sequence_geometry import Pose
    from data._trajectory import DepthRange
    from data.compositor import ObjectTrack, Scene

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
    assert scene.objects[0].depth_start is not None
    assert scene.objects[0].depth_end is not None
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
            assert obj.depth_start is not None
            assert obj.depth_end is not None
            grew = obj.pose_end.scale > obj.pose_start.scale
            came_closer = obj.depth_end.centre > obj.depth_start.centre
            assert grew == came_closer, (
                f"seed {seed}: scale "
                f"{obj.pose_start.scale:.3f}->{obj.pose_end.scale:.3f} but "
                f"disparity {obj.depth_start.centre:.3f}->"
                f"{obj.depth_end.centre:.3f}"
            )
            checked += 1
    assert checked == 80


def test_unrestricted_scene_is_collision_free(tmp_path) -> None:
    # Goal 5.
    from data._collision import pair_collides
    from data._sequence_geometry import EASING_FNS, build_fg_homography, warp_pillow

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
            assert obj.depth_start is not None
            assert obj.depth_end is not None
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
            assert obj.depth_start is not None
            assert obj.depth_end is not None
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
    import data.compositor as compositor_module
    from data._sequence_geometry import SampleConfig

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
    assert "depth_mode" not in header
    assert int(data_row[header.index("n_range_fallbacks")]) >= 0


def test_generate_dataset_skips_a_sequence_it_cannot_sample(
    tmp_path,
    monkeypatch,
) -> None:
    # Goal 8, writer half. A raising sample_scene must cost one sequence, not
    # the whole run, and the surviving sequences keep their seed-derived names.
    import data.generate_dataset as writer_module
    from data.compositor import CollisionRetriesExhausted

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


def test_save_frame_writes_every_mask_it_is_given(tmp_path) -> None:
    # This replaces a guard that refused more than three masks. The format no
    # longer truncates, so the test that mattered is now the positive one.
    from data.compositor import RenderedFrame
    from data.generate_dataset import _save_frame

    size = 8
    frame = RenderedFrame(
        rgb=np.zeros((size, size, 3), dtype=np.float32),
        alpha=np.zeros((size, size), dtype=np.float32),
        disparity=np.full((size, size), 0.5, dtype=np.float32),
        object_alphas=[
            np.full((size, size), 0.2 * (i + 1), dtype=np.float32) for i in range(7)
        ],
    )
    for d in ("aif", "alp", "disp"):
        (tmp_path / d).mkdir()
    _save_frame(frame, "01", tmp_path / "aif", tmp_path / "alp", tmp_path / "disp")

    pages = read_alpha_tiff(tmp_path / "alp" / "01.tif")
    assert len(pages) == 7
    assert read_disparity_png(tmp_path / "disp" / "01.png").mean() == pytest.approx(
        0.5,
        abs=1e-4,
    )


def test_generate_dataset_still_accepts_three_objects(tmp_path) -> None:
    library = tmp_path / "lib"
    _tiny_library(library, n_fg=3, half=4)
    out = tmp_path / "synth"
    written = generate_dataset(
        library_root=library,
        output=out,
        count=1,
        n_frames=2,
        size=32,
        seed=0,
        n_objects_min=3,
        n_objects_max=3,
    )
    assert written == 1
    assert len(read_alpha_tiff(out / "sequences" / "0001" / "alpha" / "01.tif")) == 3
