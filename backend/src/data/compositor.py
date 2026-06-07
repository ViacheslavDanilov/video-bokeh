"""Stage B: sample a scene from the library and render aligned RGB/alpha/depth.

Depth is never re-estimated here: each object's precomputed full-frame disparity
is warped by the same homography as its RGBA, scaled within a disjoint depth slot
by the linear zoom->disparity law, and painter-composited. Disjoint slots make
depth collisions structurally impossible.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

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

_BAND_WIDTH = 0.10


@dataclass
class ObjectTrack:
    asset: ForegroundAsset
    slot: tuple[float, float]
    pose_start: Pose
    pose_end: Pose
    easing: str
    scale_ref: float


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


@dataclass
class RenderedFrame:
    rgb: np.ndarray  # (H, W, 3) float32 in [0, 255]
    alpha: np.ndarray  # (H, W) float32 union alpha
    disparity: np.ndarray  # (H, W) float32 in [0, 1]


def sample_scene(
    library_root: Path,
    seed: int,
    n_frames: int,
    size: int,
    n_objects: int,
    cfg: SampleConfig | None = None,
    bg_band_top: float = 0.05,
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
    objects: list[ObjectTrack] = []
    for idx, fid in enumerate(chosen_fg):
        asset = load_foreground(library_root, fid)
        pose_start = sample_fg_pose(rng, cfg)
        pose_end = sample_fg_pose(rng, cfg)
        easing = rng.choice(cfg.easings)
        # Each object claims a distinct, disjoint slot (collision-proof).
        slot = slots[idx]
        objects.append(
            ObjectTrack(
                asset=asset,
                slot=slot,
                pose_start=pose_start,
                pose_end=pose_end,
                easing=easing,
                scale_ref=pose_start.scale,
            ),
        )
    # Paint order: farthest (lowest disparity band) drawn first.
    objects.sort(key=lambda o: o.slot[0])

    return Scene(
        background=background,
        objects=objects,
        bg_pose_start=sample_bg_pose(rng, cfg),
        bg_pose_end=sample_bg_pose(rng, cfg),
        bg_easing=rng.choice(cfg.easings),
        n_frames=n_frames,
        size=size,
        bg_band_top=bg_band_top,
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

        for obj in scene.objects:
            ease = EASING_FNS[obj.easing](t)
            pose = obj.pose_start.lerp(obj.pose_end, ease)
            fg_h = build_fg_homography(pose, obj.asset.rgb.size[0], size)

            warped_rgba = np.asarray(
                warp_pillow(obj.asset.rgb, fg_h, size),
                dtype=np.float32,
            )
            a = warped_rgba[..., 3] / 255.0
            warped_depth = warp_depth(obj.asset.depth, fg_h, size)

            band_lo, band_hi = scaled_band(
                obj.slot[0],
                obj.slot[1],
                scale_t=pose.scale,
                scale_ref=obj.scale_ref,
            )
            obj_disp = place_in_band(
                warped_depth,
                a,
                band_lo,
                band_hi,
                band_width=_BAND_WIDTH,
            )

            a3 = a[..., None]
            rgb = a3 * warped_rgba[..., :3] + (1.0 - a3) * rgb
            union_alpha = np.maximum(union_alpha, a)
            disparity = a * obj_disp + (1.0 - a) * disparity

        frames.append(
            RenderedFrame(
                rgb=rgb.astype(np.float32),
                alpha=union_alpha.astype(np.float32),
                disparity=np.clip(disparity, 0.0, 1.0).astype(np.float32),
            ),
        )
    return frames
