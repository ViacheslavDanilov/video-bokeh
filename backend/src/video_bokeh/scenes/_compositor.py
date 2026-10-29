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
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from video_bokeh.core._collision import pair_collides
from video_bokeh.core._fusion import (
    BG_BAND_TOP,
    assign_depth_slots,
    bg_normalize,
    place_in_band,
)
from video_bokeh.core._library import (
    BACKGROUNDS,
    FOREGROUNDS,
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
    homography_flow,
    sample_bg_pose,
    sample_fg_pose,
    warp_depth,
    warp_pillow,
)
from video_bokeh.core._split import TRAIN, in_split
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
    range_fallback: bool = False


@dataclass
class Scene:
    background: BackgroundAsset
    objects: list[ObjectTrack]
    bg_pose_start: Pose
    bg_pose_end: Pose
    bg_easing: str
    n_frames: int
    size: int
    bg_band_top: float = BG_BAND_TOP
    n_rejections: int = 0
    n_range_fallbacks: int = 0


@dataclass
class FrameLayers:
    """A frame before compositing: the whole background and each whole object.

    Objects are indexed like ``RenderedFrame.object_alphas``, which holds their alpha
    masks, and each object's color and disparity are zero outside its alpha mask.
    Compositing the objects over the background in ``paint_order`` gives back the frame.
    """

    background_rgb: np.ndarray  # (H, W, 3) float32 in [0, 255]
    background_disparity: np.ndarray  # (H, W) float32 in [0, 1]
    object_rgbs: list[np.ndarray]  # (H, W, 3) float32 in [0, 255], one per object
    object_disparities: list[np.ndarray]  # (H, W) float32 in [0, 1], one per object
    paint_order: list[int]  # object indices, far to near


@dataclass
class RenderedFrame:
    rgb: np.ndarray  # (H, W, 3) float32 in [0, 255]
    alpha: np.ndarray  # (H, W) float32 union alpha
    disparity: np.ndarray  # (H, W) float32 in [0, 1]
    object_alphas: list[np.ndarray] = field(
        default_factory=list,
    )  # one per object, indexed by position in Scene.objects
    layers: FrameLayers | None = None  # only when render_scene is asked for them
    #: (H, W, 2) float32, pixels to the next frame, from the front-most surface: only when
    #: asked for, and never on the last frame, which has no next.
    flow: np.ndarray | None = None
    #: (H, W, 2) float32, pixels to the previous frame, from the front-most surface: only
    #: when asked for, and never on the first frame, which has no previous.
    flow_back: np.ndarray | None = None
    #: (H, W) bool, True where the front-most surface is not visible in the next frame:
    #: only when asked for, and never on the last frame.
    occlusion: np.ndarray | None = None


def library_ids(library_root: Path, split: str = TRAIN) -> tuple[list[str], list[str]]:
    """The ids of the foregrounds and of the backgrounds in ``split``.

    One listing of the library, which a caller that samples many scenes makes once and
    passes to every ``sample_scene``: a full library is tens of thousands of folders.
    """
    return (
        in_split(list_foregrounds(library_root), FOREGROUNDS, split),
        in_split(list_backgrounds(library_root), BACKGROUNDS, split),
    )


def sample_scene(
    library_root: Path,
    seed: int,
    n_frames: int,
    size: int,
    n_objects: int,
    cfg: SampleConfig | None = None,
    bg_band_top: float = BG_BAND_TOP,
    split: str = TRAIN,
    ids: tuple[list[str], list[str]] | None = None,
) -> Scene:
    """Sample objects, a background, poses, easings, and depth trajectories.

    The assets are drawn from ``split``, ``train``, ``test`` or ``all``. ``ids`` is
    ``library_ids(library_root, split)`` when the caller listed the library already;
    without it, the library is listed here.
    """
    cfg = cfg or SampleConfig()
    rng = random.Random(f"scene:{seed}")

    fg_ids, bg_ids = ids or library_ids(library_root, split)
    if not fg_ids or not bg_ids:
        raise SystemExit(
            f"library at {library_root} has no {split} foregrounds/backgrounds",
        )

    n_objects = min(n_objects, len(fg_ids))
    chosen_fg = rng.sample(fg_ids, n_objects)
    background = load_background(library_root, rng.choice(bg_ids))

    slots = assign_depth_slots(n_objects, bg_band_top=bg_band_top)
    # Loaded once, outside the retry loop: a rejected trajectory set keeps the
    # same assets, so re-decoding the PNGs on every attempt is pure I/O.
    assets = [load_foreground(library_root, fid) for fid in chosen_fg]

    def _build_objects(attempt_rng: random.Random) -> tuple[list[ObjectTrack], int]:
        objs: list[ObjectTrack] = []
        fallbacks = 0
        for idx, asset in enumerate(assets):
            # The poses and the easing are drawn in this order, so a seed keeps its
            # sequence only while this order does.
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
                    range_fallback=used_fallback,
                ),
            )
        # Far-to-near at frame 1. render_scene derives paint order per frame,
        # so this only fixes which alpha layer each object owns for the clip.
        objs.sort(key=lambda o: o.depth_start.center)
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


def render_scene(
    scene: Scene,
    layers: bool = False,
    flow: bool = False,
    flow_back: bool = False,
    occlusion: bool = False,
) -> list[RenderedFrame]:
    """Render every frame: warp the precomputed triplet, band depth, composite.

    With ``layers``, each frame also keeps what it was composited from. Off by default:
    the layers hold several more copies of the frame, which a caller that composites
    only would carry for nothing.

    With ``flow``, each frame but the last carries its forward optical flow. Every layer
    moves by a known homography, so the flow is exact: per pixel, the motion of the
    front-most surface, the last-painted object whose alpha is at least 0.5 there, else
    the background's. The flow itself marks no occlusion. With ``flow_back``, each frame
    but the first carries its backward flow the same way: where the front-most surface at
    each pixel was in the previous frame. With ``occlusion``, each frame but the last
    carries a mask of the pixels whose surface is not visible in the next frame, because
    it leaves the frame or another surface is in front of it there; ``occlusion_mask``
    says how.
    """
    return list(iter_frames(scene, layers, flow, flow_back, occlusion))


def occlusion_mask(
    front_now: np.ndarray,
    front_next: np.ndarray,
    flow: np.ndarray,
) -> np.ndarray:
    """Where a frame's front-most surface is not visible in the next frame.

    ``front_now`` and ``front_next`` say which surface is in front at each pixel of the
    two frames, an object's index or -1 for the background, and ``flow`` is the forward
    flow. A pixel is occluded when it lands outside the next frame, or when the surface
    at the nearest pixel to where it lands is not the one it carries.
    """
    h, w = front_now.shape
    ys, xs = np.mgrid[0:h, 0:w]
    # Plain nearest: np.round would send ties to the even pixel.
    x = np.floor(xs + flow[..., 0] + 0.5).astype(int)
    y = np.floor(ys + flow[..., 1] + 0.5).astype(int)
    inside = (x >= 0) & (x < w) & (y >= 0) & (y < h)
    landed = front_next[np.clip(y, 0, h - 1), np.clip(x, 0, w - 1)]
    return ~inside | (landed != front_now)


def _background_homography(scene: Scene, t: float) -> np.ndarray:
    """The background's forward homography at time ``t`` in [0, 1]."""
    pose = scene.bg_pose_start.lerp(scene.bg_pose_end, EASING_FNS[scene.bg_easing](t))
    return build_bg_homography(pose, scene.background.rgb.size[0], scene.size)


def _object_homography(scene: Scene, obj: ObjectTrack, t: float) -> np.ndarray:
    """An object's forward homography at time ``t`` in [0, 1]."""
    pose = obj.pose_start.lerp(obj.pose_end, EASING_FNS[obj.easing](t))
    return build_fg_homography(pose, obj.asset.rgb.size[0], scene.size)


def _draw_order(
    scene: Scene,
    t: float,
) -> tuple[list[tuple[float, float]], list[int]]:
    """Each object's target disparity band at time ``t``, and the objects far to near.

    The bands are indexed by object. The order sorts them by the middle of the band, low
    disparity first, which is the order they are painted in.
    """
    bands = []
    for obj in scene.objects:
        r = obj.depth_start.lerp(obj.depth_end, EASING_FNS[obj.easing](t))
        bands.append((r.mind, r.maxd))
    order = sorted(
        range(len(bands)), key=lambda idx: (bands[idx][0] + bands[idx][1]) / 2.0
    )
    return bands, order


def iter_frames(
    scene: Scene,
    layers: bool = False,
    flow: bool = False,
    flow_back: bool = False,
    occlusion: bool = False,
) -> Iterator[RenderedFrame]:
    """``render_scene`` one frame at a time, so a writer never holds the whole clip."""
    size = scene.size

    for i in range(scene.n_frames):
        t = 0.0 if scene.n_frames == 1 else i / (scene.n_frames - 1)
        # The next frame's time, when there is one and the flow toward it is wanted,
        # and the previous frame's likewise.
        t_next = (
            (i + 1) / (scene.n_frames - 1)
            if (flow or occlusion) and i + 1 < scene.n_frames
            else None
        )
        t_prev = (i - 1) / (scene.n_frames - 1) if flow_back and i > 0 else None

        bg_h = _background_homography(scene, t)
        frame_flow = None
        if t_next is not None:
            frame_flow = homography_flow(
                bg_h, _background_homography(scene, t_next), size
            )
        frame_flow_back = None
        if t_prev is not None:
            frame_flow_back = homography_flow(
                bg_h,
                _background_homography(scene, t_prev),
                size,
            )
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
        n_kept = len(scene.objects) if layers else 0
        object_rgbs = [np.zeros((size, size, 3), dtype=np.float32)] * n_kept
        object_disparities = [np.zeros((size, size), dtype=np.float32)] * n_kept
        background_disparity = disparity

        bands, draw_order = _draw_order(scene, t)
        # The surface in front at each pixel, an object's index or -1, for the occlusion
        # mask; the same rule the flow uses.
        front_now = np.full((size, size), -1)
        for idx in draw_order:
            obj = scene.objects[idx]
            band_lo, band_hi = bands[idx]
            fg_h = _object_homography(scene, obj, t)

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
            )

            a3 = a[..., None]
            rgb = a3 * warped_rgba[..., :3] + (1.0 - a3) * rgb
            union_alpha = np.maximum(union_alpha, a)
            disparity = a * obj_disp + (1.0 - a) * disparity
            object_alphas[idx] = a.astype(np.float32)
            front = a >= 0.5
            front_now[front] = idx
            if frame_flow is not None and t_next is not None:
                frame_flow[front] = homography_flow(
                    fg_h,
                    _object_homography(scene, obj, t_next),
                    size,
                )[front]
            if frame_flow_back is not None and t_prev is not None:
                frame_flow_back[front] = homography_flow(
                    fg_h,
                    _object_homography(scene, obj, t_prev),
                    size,
                )[front]
            if layers:
                inside = a > 0
                object_rgbs[idx] = np.where(inside[..., None], warped_rgba[..., :3], 0)
                object_disparities[idx] = np.where(inside, obj_disp, 0).astype(
                    np.float32,
                )

        frame_occlusion = None
        if occlusion and frame_flow is not None and t_next is not None:
            front_next = np.full((size, size), -1)
            for idx in _draw_order(scene, t_next)[1]:
                obj = scene.objects[idx]
                h_next = _object_homography(scene, obj, t_next)
                a_next = np.asarray(
                    warp_pillow(obj.asset.rgb.getchannel("A"), h_next, size),
                    dtype=np.float32,
                )
                front_next[a_next >= 127.5] = idx
            frame_occlusion = occlusion_mask(front_now, front_next, frame_flow)

        yield RenderedFrame(
            rgb=rgb.astype(np.float32),
            alpha=union_alpha.astype(np.float32),
            disparity=np.clip(disparity, 0.0, 1.0).astype(np.float32),
            object_alphas=object_alphas,
            layers=FrameLayers(
                background_rgb=bg_rgb,
                background_disparity=background_disparity,
                object_rgbs=object_rgbs,
                object_disparities=object_disparities,
                paint_order=draw_order,
            )
            if layers
            else None,
            flow=frame_flow if flow else None,
            flow_back=frame_flow_back,
            occlusion=frame_occlusion,
        )
