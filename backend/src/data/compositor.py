"""Stage B: sample a scene from the library and render aligned RGB/alpha/depth.

Depth is never re-estimated here: each object's precomputed full-frame disparity
is warped by the same homography as its RGBA, scaled within a disjoint depth slot
by the linear zoom->disparity law, and painter-composited. Disjoint slots make
depth collisions structurally impossible.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from data._collision import pair_collides
from data._depth_track import DepthTrack, active_interval, scale_at
from data._fusion import assign_depth_slots, bg_normalize, place_in_band, scaled_band
from data._library import (
    BackgroundAsset,
    ForegroundAsset,
    list_backgrounds,
    list_foregrounds,
    load_background,
    load_foreground,
)
from data._sequence_geometry import (
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

_ACTIVE_WIDTH = 0.08
_Z_NEAR = 0.6
_Z_FAR = 1.6
_MAX_SAMPLE_TRIES = 50


@dataclass
class ObjectTrack:
    asset: ForegroundAsset
    slot: tuple[float, float]
    pose_start: Pose
    pose_end: Pose
    easing: str
    scale_ref: float
    depth_track: DepthTrack | None = None


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


@dataclass
class RenderedFrame:
    rgb: np.ndarray  # (H, W, 3) float32 in [0, 255]
    alpha: np.ndarray  # (H, W) float32 union alpha
    disparity: np.ndarray  # (H, W) float32 in [0, 1]
    object_alphas: list[np.ndarray] = field(
        default_factory=list,
    )  # per-object, far→near


def sample_scene(
    library_root: Path,
    seed: int,
    n_frames: int,
    size: int,
    n_objects: int,
    cfg: SampleConfig | None = None,
    bg_band_top: float = 0.05,
    depth_mode: str = "fixed",
) -> Scene:
    """Sample objects, a background, poses, easings, and disjoint depth slots."""
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

    def _build_objects(attempt_rng: random.Random) -> list[ObjectTrack]:
        objs: list[ObjectTrack] = []
        for idx, fid in enumerate(chosen_fg):
            asset = load_foreground(library_root, fid)
            pose_start = sample_fg_pose(attempt_rng, cfg)
            pose_end = sample_fg_pose(attempt_rng, cfg)
            easing = attempt_rng.choice(cfg.easings)
            slot = slots[idx]
            depth_track = None
            if depth_mode == "dynamic":
                zr = attempt_rng.uniform(_Z_NEAR, _Z_FAR)
                depth_track = DepthTrack(
                    env_lo=slot[0],
                    env_hi=slot[1],
                    active_width=_ACTIVE_WIDTH,
                    z_start=attempt_rng.uniform(_Z_NEAR, _Z_FAR),
                    z_end=attempt_rng.uniform(_Z_NEAR, _Z_FAR),
                    z_ref=zr,
                    scale_ref=pose_start.scale,
                    disp_ref=(slot[0] + slot[1]) / 2.0,
                )
            objs.append(
                ObjectTrack(
                    asset=asset,
                    slot=slot,
                    pose_start=pose_start,
                    pose_end=pose_end,
                    easing=easing,
                    scale_ref=pose_start.scale,
                    depth_track=depth_track,
                ),
            )
        # Paint order: farthest (lowest disparity band) drawn first.
        objs.sort(key=lambda o: o.slot[0])
        return objs

    def _has_collision(objs: list[ObjectTrack]) -> bool:
        if depth_mode != "dynamic" or len(objs) < 2:
            return False
        for i in range(n_frames):
            t = 0.0 if n_frames == 1 else i / (n_frames - 1)
            warped = []
            for o in objs:
                ease = EASING_FNS[o.easing](t)
                pose = o.pose_start.lerp(o.pose_end, ease)
                h = build_fg_homography(pose, o.asset.rgb.size[0], size)
                a = np.asarray(warp_pillow(o.asset.rgb, h, size))[..., 3] / 255.0
                assert o.depth_track is not None
                warped.append((a, active_interval(o.depth_track, ease)))
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
    objects = _build_objects(rng)
    while _has_collision(objects):
        n_rejections += 1
        if n_rejections >= _MAX_SAMPLE_TRIES:
            break
        objects = _build_objects(rng)

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
        object_alphas: list[np.ndarray] = []

        def _centre(o: ObjectTrack, _t: float = t) -> float:
            ease = EASING_FNS[o.easing](_t)
            if o.depth_track is not None:
                lo, hi = active_interval(o.depth_track, ease)
                return (lo + hi) / 2.0
            band_lo, band_hi = scaled_band(
                o.slot[0],
                o.slot[1],
                active_width=_ACTIVE_WIDTH,
                scale_t=o.pose_start.lerp(o.pose_end, ease).scale,
                scale_ref=o.scale_ref,
            )
            return (band_lo + band_hi) / 2.0

        draw_order = sorted(scene.objects, key=_centre)  # far (low disp) first
        for obj in draw_order:
            ease = EASING_FNS[obj.easing](t)
            pose = obj.pose_start.lerp(obj.pose_end, ease)
            if obj.depth_track is not None:
                pose = replace(pose, scale=scale_at(obj.depth_track, ease))
                band_lo, band_hi = active_interval(obj.depth_track, ease)
            else:
                band_lo, band_hi = scaled_band(
                    obj.slot[0],
                    obj.slot[1],
                    active_width=_ACTIVE_WIDTH,
                    scale_t=pose.scale,
                    scale_ref=obj.scale_ref,
                )
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
                band_width=_ACTIVE_WIDTH,
            )

            a3 = a[..., None]
            rgb = a3 * warped_rgba[..., :3] + (1.0 - a3) * rgb
            union_alpha = np.maximum(union_alpha, a)
            disparity = a * obj_disp + (1.0 - a) * disparity
            object_alphas.append(a.astype(np.float32))

        frames.append(
            RenderedFrame(
                rgb=rgb.astype(np.float32),
                alpha=union_alpha.astype(np.float32),
                disparity=np.clip(disparity, 0.0, 1.0).astype(np.float32),
                object_alphas=object_alphas,
            ),
        )
    return frames
