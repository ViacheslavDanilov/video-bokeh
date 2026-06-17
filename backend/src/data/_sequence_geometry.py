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


def warp_depth(arr: np.ndarray, h: np.ndarray, out_size: int) -> np.ndarray:
    """Warp a float (H, W) disparity map with forward homography ``h``.

    Mirrors ``warp_pillow`` but for single-channel float data via Pillow's
    'F' mode, so depth moves pixel-aligned with the RGBA warp.
    """
    inv = np.linalg.inv(h)
    inv = inv / inv[2, 2]
    coeffs = tuple(inv.flatten()[:8])
    img = Image.fromarray(np.asarray(arr, dtype=np.float32), mode="F")
    warped = img.transform(
        (out_size, out_size),
        Image.Transform.PERSPECTIVE,
        coeffs,
        resample=Image.Resampling.BILINEAR,
    )
    return np.asarray(warped, dtype=np.float32)


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
