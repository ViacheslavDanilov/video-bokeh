"""Scene geometry shared by sequence rendering and depth fusion.

This private module is the single source of truth for pose math, easing
functions, homography construction, foreground/background warping, asset
preparation, object-track construction, and deterministic scene replay.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Pose:
    """Foreground pose on the output frame.

    All fields are in normalized / degree units so they compose cleanly.
    tx, ty   - object center offset from frame center, in fractions of frame.
    scale    - object size as fraction of frame edge (1.0 => edge-to-edge).
    rot_deg  - in-plane rotation, degrees.
    tilt_x   - 3D rotation around horizontal axis, degrees (perspective).
    tilt_y   - 3D rotation around vertical axis, degrees.
    """

    tx: float = 0.0
    ty: float = 0.0
    scale: float = 0.5
    rot_deg: float = 0.0
    tilt_x: float = 0.0
    tilt_y: float = 0.0

    def lerp(self, other: Pose, t: float) -> Pose:
        return Pose(
            tx=_lerp(self.tx, other.tx, t),
            ty=_lerp(self.ty, other.ty, t),
            scale=_lerp(self.scale, other.scale, t),
            rot_deg=_lerp(self.rot_deg, other.rot_deg, t),
            tilt_x=_lerp(self.tilt_x, other.tilt_x, t),
            tilt_y=_lerp(self.tilt_y, other.tilt_y, t),
        )


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


# fmt: off
EASING_FNS: dict[str, Callable[[float], float]] = {
    "easeInSine": lambda t: 1.0 - math.cos(t * math.pi / 2.0),
    "easeOutSine": lambda t: math.sin(t * math.pi / 2.0),
    "easeInOutSine": lambda t: 0.5 * (1.0 - math.cos(math.pi * t)),
    "easeInCubic": lambda t: t**3,
    "easeOutCubic": lambda t: 1.0 - (1.0 - t) ** 3,
    "easeInOutCubic": lambda t: 4.0 * t**3 if t < 0.5 else 1.0 - 4.0 * (1.0 - t) ** 3,
    "easeInQuint": lambda t: t**5,
    "easeOutQuint": lambda t: 1.0 - (1.0 - t) ** 5,
    "easeInOutQuint": lambda t: 16.0 * t**5 if t < 0.5 else 1.0 - 16.0 * (1.0 - t) ** 5,
}
# fmt: on

EASING_NAMES_DEFAULT: tuple[str, ...] = tuple(EASING_FNS)

_UNIT_SQUARE = np.array(
    [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]],
    dtype=np.float64,
)


def _project_perspective(
    corners: np.ndarray,
    focal: float,
    tilt_x_deg: float,
    tilt_y_deg: float,
) -> np.ndarray:
    """Lift 2D corners to z = focal, tilt around X then Y, project back to 2D."""
    pts3d = np.column_stack([corners, np.full(len(corners), focal)])
    a = math.radians(tilt_x_deg)
    b = math.radians(tilt_y_deg)
    rx = np.array(
        [[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]],
    )
    ry = np.array(
        [[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]],
    )
    pts3d = pts3d @ rx.T @ ry.T
    return pts3d[:, :2] * (focal / pts3d[:, 2:3])


def _rotate_2d(pts: np.ndarray, rot_deg: float) -> np.ndarray:
    """In-plane rotation around the origin."""
    theta = math.radians(rot_deg)
    rot = np.array(
        [[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]],
    )
    return pts @ rot.T


def _solve_homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Forward 3x3 homography mapping src (N,2) -> dst (N,2). N must be 4."""
    A = np.empty((8, 8), dtype=np.float64)
    b = np.empty(8, dtype=np.float64)
    for i, ((x, y), (u, v)) in enumerate(zip(src, dst, strict=True)):
        A[2 * i] = [x, y, 1, 0, 0, 0, -u * x, -u * y]
        A[2 * i + 1] = [0, 0, 0, x, y, 1, -v * x, -v * y]
        b[2 * i] = u
        b[2 * i + 1] = v
    h = np.linalg.solve(A, b)
    return np.array(
        [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]],
        dtype=np.float64,
    )


def _fg_target_corners(pose: Pose, frame_size: int) -> np.ndarray:
    """Where the object's 4 corners land on the output frame."""
    f = frame_size
    pts = _project_perspective(_UNIT_SQUARE, 1.8, pose.tilt_x, pose.tilt_y)
    pts = pts * (pose.scale * f)
    pts = _rotate_2d(pts, pose.rot_deg)
    cx = pose.tx * f + f / 2.0
    cy = pose.ty * f + f / 2.0
    return pts + np.array([cx, cy])


def build_fg_homography(pose: Pose, src_size: int, frame_size: int) -> np.ndarray:
    """Forward homography: source-image pixels -> output-frame pixels."""
    src_corners = np.array(
        [[0, 0], [src_size, 0], [src_size, src_size], [0, src_size]],
        dtype=np.float64,
    )
    dst_corners = _fg_target_corners(pose, frame_size)
    return _solve_homography(src_corners, dst_corners)


def build_bg_homography(pose: Pose, src_size: int, frame_size: int) -> np.ndarray:
    """Forward homography for a background."""
    f = frame_size
    pts = _project_perspective(_UNIT_SQUARE, 2.5, pose.tilt_x, pose.tilt_y)
    pts = pts * (f / pose.scale)
    pts = _rotate_2d(pts, pose.rot_deg)
    cx = pose.tx * f + src_size / 2.0
    cy = pose.ty * f + src_size / 2.0
    src_region = pts + np.array([cx, cy])
    dst_corners = np.array([[0, 0], [f, 0], [f, f], [0, f]], dtype=np.float64)
    return _solve_homography(src_region, dst_corners)


def warp_pillow(img: Image.Image, h: np.ndarray, out_size: int) -> Image.Image:
    """Apply forward homography h using Pillow's PERSPECTIVE transform."""
    inv = np.linalg.inv(h)
    inv = inv / inv[2, 2]
    coeffs = tuple(inv.flatten()[:8])
    return img.transform(
        (out_size, out_size),
        Image.Transform.PERSPECTIVE,
        coeffs,
        resample=Image.Resampling.BILINEAR,
    )


def resize_shortest_side_and_center_crop(img: Image.Image, size: int) -> Image.Image:
    w, h = img.size
    if w < h:
        new_w = size
        new_h = max(size, round(h * size / w))
    else:
        new_h = size
        new_w = max(size, round(w * size / h))
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - size) // 2
    top = (new_h - size) // 2
    return img.crop((left, top, left + size, top + size))


@dataclass
class SampleConfig:
    scale_min: float = 0.20
    scale_max: float = 0.80
    max_exit: float = 0.20
    max_rot: float = 25.0
    max_tilt: float = 15.0
    bg_pan: float = 0.10
    bg_zoom: float = 0.10
    bg_margin: float = 0.15
    easings: tuple[str, ...] = EASING_NAMES_DEFAULT


def _tx_bound(scale: float, max_exit: float) -> float:
    """Max absolute value for tx given scale and max_exit, clamped >= 0."""
    return max(0.0, 0.5 - scale * (0.5 - max_exit))


def sample_fg_pose(rng: random.Random, cfg: SampleConfig) -> Pose:
    scale = rng.uniform(cfg.scale_min, cfg.scale_max)
    bound = _tx_bound(scale, cfg.max_exit)
    return Pose(
        tx=rng.uniform(-bound, bound),
        ty=rng.uniform(-bound, bound),
        scale=scale,
        rot_deg=rng.uniform(-cfg.max_rot, cfg.max_rot),
        tilt_x=rng.uniform(-cfg.max_tilt, cfg.max_tilt),
        tilt_y=rng.uniform(-cfg.max_tilt, cfg.max_tilt),
    )


def sample_bg_pose(rng: random.Random, cfg: SampleConfig) -> Pose:
    return Pose(
        tx=rng.uniform(-cfg.bg_pan, cfg.bg_pan),
        ty=rng.uniform(-cfg.bg_pan, cfg.bg_pan),
        scale=rng.uniform(1.0, 1.0 + cfg.bg_zoom),
        rot_deg=rng.uniform(-cfg.max_tilt * 0.2, cfg.max_tilt * 0.2),
        tilt_x=rng.uniform(-cfg.max_tilt * 0.2, cfg.max_tilt * 0.2),
        tilt_y=rng.uniform(-cfg.max_tilt * 0.2, cfg.max_tilt * 0.2),
    )


def prepare_background(path: Path, frame_size: int, margin: float) -> Image.Image:
    src_size = int(round(frame_size * (1.0 + 2.0 * margin)))
    img = Image.open(path).convert("RGB")
    return resize_shortest_side_and_center_crop(img, src_size)


def prepare_foreground(path: Path, src_size: int) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    return resize_shortest_side_and_center_crop(img, src_size)


@dataclass
class ObjectTrack:
    ref: str
    img: Image.Image
    source_size: int
    depth: float
    pose_start: Pose
    pose_end: Pose
    easing: str = "easeInOutSine"


def build_object_tracks(
    spec,
    fg_root: Path,
    frame_size: int,
    rng: random.Random,
    cfg: SampleConfig,
) -> list[ObjectTrack]:
    """Load foregrounds and sample per-object poses + depths.

    The RNG draw order (pose_start, pose_end, depth) per object is part of the
    deterministic contract. Returned tracks are sorted back-to-front (largest
    depth first) for paint order.
    """
    objs: list[ObjectTrack] = []
    for ref in spec.object_refs:
        fg_img = prepare_foreground(fg_root / "images" / ref, frame_size)
        pose_start = sample_fg_pose(rng, cfg)
        pose_end = sample_fg_pose(rng, cfg)
        depth = rng.random()
        objs.append(
            ObjectTrack(
                ref=ref,
                img=fg_img,
                source_size=frame_size,
                depth=depth,
                pose_start=pose_start,
                pose_end=pose_end,
            ),
        )
    objs.sort(key=lambda o: -o.depth)
    return objs


@dataclass
class ReplayedFrame:
    """One rendered frame, pre-composite."""

    bg_rgb: Image.Image
    object_rgbas: list[Image.Image]


@dataclass
class SceneReplay:
    """Full deterministic replay of one sequence's geometry."""

    frames: list[ReplayedFrame]
    object_depths: list[float]
    channel_refs: list[str]
    bg_easing: str
    object_easings: list[str]


def replay_scene(
    spec,
    fg_root: Path,
    bg_root: Path,
    cfg: SampleConfig,
    *,
    validate_channel_refs: bool = False,
) -> SceneReplay:
    """Replay a sequence's scene geometry without writing files."""
    rng = random.Random(f"poses:{spec.seed}")
    frame_size = spec.size

    bg_img = prepare_background(
        bg_root / "images" / spec.bg_ref,
        frame_size,
        cfg.bg_margin,
    )
    bg_src_size = bg_img.size[0]

    objs = build_object_tracks(spec, fg_root, frame_size, rng, cfg)
    channel_refs = [obj.ref for obj in objs]
    channel_refs_match = (
        bool(spec.channel_refs) and list(spec.channel_refs) == channel_refs
    )
    if validate_channel_refs and spec.channel_refs and not channel_refs_match:
        raise ValueError(
            f"sequence {spec.seq_id}: channel_refs do not match replayed paint order",
        )

    bg_start = sample_bg_pose(rng, cfg)
    bg_end = sample_bg_pose(rng, cfg)

    bg_easing = spec.bg_easing or rng.choice(cfg.easings)
    if spec.object_easings:
        object_easings = list(spec.object_easings)
    else:
        object_easings = [rng.choice(cfg.easings) for _ in objs]
    for obj, name in zip(objs, object_easings, strict=True):
        obj.easing = name
    bg_easing_fn = EASING_FNS[bg_easing]

    frames: list[ReplayedFrame] = []
    for i in range(spec.n_frames):
        t = 0.0 if spec.n_frames == 1 else i / (spec.n_frames - 1)
        bg_pose = bg_start.lerp(bg_end, bg_easing_fn(t))
        bg_warp = warp_pillow(
            bg_img,
            build_bg_homography(bg_pose, bg_src_size, frame_size),
            frame_size,
        )
        object_rgbas: list[Image.Image] = []
        for obj in objs:
            pose = obj.pose_start.lerp(obj.pose_end, EASING_FNS[obj.easing](t))
            fg_warp = warp_pillow(
                obj.img,
                build_fg_homography(pose, obj.source_size, frame_size),
                frame_size,
            )
            object_rgbas.append(fg_warp)
        frames.append(ReplayedFrame(bg_rgb=bg_warp, object_rgbas=object_rgbas))

    if spec.object_depths and (not spec.channel_refs or channel_refs_match):
        object_depths = list(spec.object_depths)
        if len(object_depths) != len(objs):
            raise ValueError(
                f"sequence {spec.seq_id}: {len(object_depths)} object_depths for "
                f"{len(objs)} objects",
            )
    else:
        object_depths = [obj.depth for obj in objs]

    return SceneReplay(
        frames=frames,
        object_depths=object_depths,
        channel_refs=channel_refs,
        bg_easing=bg_easing,
        object_easings=object_easings,
    )
