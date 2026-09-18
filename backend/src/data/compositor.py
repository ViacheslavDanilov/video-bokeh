"""Stage B: sample a scene from the library and render aligned RGB/alpha/depth.

Depth is never re-estimated here: each object's precomputed full-frame disparity
is warped by the same homography as its RGBA and remapped into the disparity
range its trajectory occupies at that frame. The assigned slot seeds frame 1
only; every later range is derived from the object's scale ratio, so objects
move freely through depth and trajectories are validated against collisions
rather than made collision-proof by construction.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from video_bokeh.core._collision import pair_collides
from video_bokeh.core._fusion import assign_depth_slots, bg_normalize, place_in_band
from video_bokeh.core._library import (
    BackgroundAsset,
    ForegroundAsset,
    list_backgrounds,
    list_foregrounds,
    load_background,
    load_foreground,
)
from video_bokeh.core._sequence_geometry import (
    EASING_FNS,
    Pose,
    SampleConfig,
    build_bg_homography,
    build_fg_homography,
    sample_bg_pose,
    sample_fg_pose,
    warp_depth,
    warp_pillow,
)
from video_bokeh.core._trajectory import DepthRange, sample_end_pose, sample_start_range

_ACTIVE_WIDTH = 0.08
_MAX_SAMPLE_TRIES = 50
_MAX_RANGE_TRIES = 100


class CollisionRetriesExhausted(RuntimeError):
    """No collision-free trajectory set was found within the retry budget.

    Raised instead of returning a scene whose objects still overlap at
    overlapping depth: such a sample has ambiguous depth ordering and would
    teach the model something untrue.
    """


@dataclass
class ObjectTrack:
    asset: ForegroundAsset
    # Kept although the renderer never reads it: it records which slot seeded frame 1,
    # which is what lets a test assert the object actually leaves it.
    slot: tuple[float, float]
    pose_start: Pose
    pose_end: Pose
    easing: str
    depth_start: DepthRange
    depth_end: DepthRange


@dataclass
class Scene:
    background: BackgroundAsset
    objects: list[ObjectTrack]
    bg_pose_start: Pose
    bg_pose_end: Pose
    bg_easing: str
    n_frames: int
    size: int
    bg_band_top: float = 0.05
    n_rejections: int = 0
    n_range_fallbacks: int = 0


@dataclass
class RenderedFrame:
    rgb: np.ndarray  # (H, W, 3) float32 in [0, 255]
    alpha: np.ndarray  # (H, W) float32 union alpha
    disparity: np.ndarray  # (H, W) float32 in [0, 1]
    object_alphas: list[np.ndarray] = field(
        default_factory=list,
    )  # one per object, indexed by position in Scene.objects


def sample_scene(
    library_root: Path,
    seed: int,
    n_frames: int,
    size: int,
    n_objects: int,
    cfg: SampleConfig | None = None,
    bg_band_top: float = 0.05,
) -> Scene:
    """Sample objects, a background, poses, easings, and depth trajectories."""
    cfg = cfg or SampleConfig()
    rng = random.Random(f"scene:{seed}")

    fg_ids = list_foregrounds(library_root)
    bg_ids = list_backgrounds(library_root)
    if not fg_ids or not bg_ids:
        raise SystemExit(f"library at {library_root} has no foregrounds/backgrounds")

    n_objects = min(n_objects, len(fg_ids))
    chosen_fg = rng.sample(fg_ids, n_objects)
    background = load_background(library_root, rng.choice(bg_ids))

    slots = assign_depth_slots(n_objects, bg_band_top=bg_band_top)
    # Loaded once, outside the retry loop: a rejected trajectory set changes
    # only the poses, so re-decoding the PNGs on every attempt is pure I/O.
    assets = [load_foreground(library_root, fid) for fid in chosen_fg]

    def _build_objects(attempt_rng: random.Random) -> tuple[list[ObjectTrack], int]:
        objs: list[ObjectTrack] = []
        fallbacks = 0
        for idx, asset in enumerate(assets):
            # These three draws, in this order, are fixed mode's RNG contract.
            # The unrestricted branch only draws after them, so switching modes
            # cannot shift the stream fixed mode sees.
            pose_start = sample_fg_pose(attempt_rng, cfg)
            pose_end = sample_fg_pose(attempt_rng, cfg)
            easing = attempt_rng.choice(cfg.easings)
            slot = slots[idx]
            depth_start = sample_start_range(
                attempt_rng,
                slot,
                min(_ACTIVE_WIDTH, slot[1] - slot[0]),
            )
            pose_end, depth_end, used_fallback = sample_end_pose(
                attempt_rng,
                cfg,
                depth_start,
                pose_start.scale,
                bg_band_top,
                _MAX_RANGE_TRIES,
            )
            fallbacks += int(used_fallback)
            objs.append(
                ObjectTrack(
                    asset=asset,
                    slot=slot,
                    pose_start=pose_start,
                    pose_end=pose_end,
                    easing=easing,
                    depth_start=depth_start,
                    depth_end=depth_end,
                ),
            )
        # Far-to-near at frame 1. render_scene derives paint order per frame,
        # so this only fixes which alpha layer each object owns for the clip.
        objs.sort(key=lambda o: o.depth_start.centre)
        return objs, fallbacks

    def _has_collision(objs: list[ObjectTrack]) -> bool:
        if len(objs) < 2:
            return False
        for i in range(n_frames):
            t = 0.0 if n_frames == 1 else i / (n_frames - 1)
            warped = []
            for o in objs:
                ease = EASING_FNS[o.easing](t)
                pose = o.pose_start.lerp(o.pose_end, ease)
                h = build_fg_homography(pose, o.asset.rgb.size[0], size)
                a = np.asarray(warp_pillow(o.asset.rgb, h, size))[..., 3] / 255.0
                r = o.depth_start.lerp(o.depth_end, ease)
                warped.append((a, (r.mind, r.maxd)))
            for x in range(len(warped)):
                for y in range(x + 1, len(warped)):
                    if pair_collides(
                        warped[x][0],
                        warped[x][1],
                        warped[y][0],
                        warped[y][1],
                    ):
                        return True
        return False

    n_rejections = 0
    objects, n_range_fallbacks = _build_objects(rng)
    while _has_collision(objects):
        n_rejections += 1
        if n_rejections >= _MAX_SAMPLE_TRIES:
            raise CollisionRetriesExhausted(
                f"seed {seed}: {len(objects)} objects still collide after "
                f"{_MAX_SAMPLE_TRIES} attempts",
            )
        objects, n_range_fallbacks = _build_objects(rng)

    return Scene(
        background=background,
        objects=objects,
        bg_pose_start=sample_bg_pose(rng, cfg),
        bg_pose_end=sample_bg_pose(rng, cfg),
        bg_easing=rng.choice(cfg.easings),
        n_frames=n_frames,
        size=size,
        bg_band_top=bg_band_top,
        n_rejections=n_rejections,
        n_range_fallbacks=n_range_fallbacks,
    )


def render_scene(scene: Scene) -> list[RenderedFrame]:
    """Render every frame: warp the precomputed triplet, band depth, composite."""
    size = scene.size
    bg_easing_fn = EASING_FNS[scene.bg_easing]
    bg_src_size = scene.background.rgb.size[0]

    frames: list[RenderedFrame] = []
    for i in range(scene.n_frames):
        t = 0.0 if scene.n_frames == 1 else i / (scene.n_frames - 1)

        bg_pose = scene.bg_pose_start.lerp(scene.bg_pose_end, bg_easing_fn(t))
        bg_h = build_bg_homography(bg_pose, bg_src_size, size)
        bg_rgb = np.asarray(
            warp_pillow(scene.background.rgb, bg_h, size),
            dtype=np.float32,
        )[..., :3]
        bg_disp = warp_depth(scene.background.depth, bg_h, size)

        rgb = bg_rgb.copy()
        union_alpha = np.zeros((size, size), dtype=np.float32)
        disparity = bg_normalize(bg_disp, bg_band_top=scene.bg_band_top)
        # Indexed by object, not by draw order: the spec fixes each object to
        # one alpha channel for the whole clip, and paint order changes per
        # frame.
        object_alphas = [
            np.zeros((size, size), dtype=np.float32) for _ in scene.objects
        ]

        def _band(idx: int, _t: float = t) -> tuple[float, float, float]:
            """Target disparity band and its width for object ``idx`` at ``_t``."""
            o = scene.objects[idx]
            ease = EASING_FNS[o.easing](_t)
            r = o.depth_start.lerp(o.depth_end, ease)
            return r.mind, r.maxd, r.width

        bands = [_band(idx) for idx in range(len(scene.objects))]
        # Far (low disparity) first.
        draw_order = sorted(
            range(len(scene.objects)),
            key=lambda idx: (bands[idx][0] + bands[idx][1]) / 2.0,
        )
        for idx in draw_order:
            obj = scene.objects[idx]
            ease = EASING_FNS[obj.easing](t)
            pose = obj.pose_start.lerp(obj.pose_end, ease)
            band_lo, band_hi, band_width = bands[idx]
            fg_h = build_fg_homography(pose, obj.asset.rgb.size[0], size)

            warped_rgba = np.asarray(
                warp_pillow(obj.asset.rgb, fg_h, size),
                dtype=np.float32,
            )
            a = warped_rgba[..., 3] / 255.0
            warped_depth = warp_depth(obj.asset.depth, fg_h, size)

            obj_disp = place_in_band(
                warped_depth,
                a,
                band_lo,
                band_hi,
                band_width=band_width,
            )

            a3 = a[..., None]
            rgb = a3 * warped_rgba[..., :3] + (1.0 - a3) * rgb
            union_alpha = np.maximum(union_alpha, a)
            disparity = a * obj_disp + (1.0 - a) * disparity
            object_alphas[idx] = a.astype(np.float32)

        frames.append(
            RenderedFrame(
                rgb=rgb.astype(np.float32),
                alpha=union_alpha.astype(np.float32),
                disparity=np.clip(disparity, 0.0, 1.0).astype(np.float32),
                object_alphas=object_alphas,
            ),
        )
    return frames
