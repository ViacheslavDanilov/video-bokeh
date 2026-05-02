#!/usr/bin/env python3
"""Generate synthetic video sequences for matting-network training.

Each sequence composites 1–3 MAGICK foregrounds (RGBA) over one BG-20k
background, with smooth keyframed perspective motion per layer. Three
pixel-aligned streams are written per frame: all-in-focus RGB (input to
Depth Anything and what the matting net sees), union alpha (matting GT),
and per-object alpha layers packed into a single RGB PNG.

Layout:

    <out>/
    ├── manifest.csv                  # one row per sequence (seed-driven + post-render channel map)
    └── sequences/
        └── 0001/
            ├── all_in_focus/01.png … 80.png    # RGB composite (input to Depth Anything)
            ├── alpha/01.png … 80.png           # union alpha (matting GT)
            └── alpha_layers/01.png … 80.png    # per-object alpha; R=ch0 (bottommost), G=ch1, B=ch2

The channel index in `alpha_layers` encodes paint order (0 = drawn first
over the background, N-1 = drawn last on top). It is NOT depth order —
non-occluding objects have arbitrary channel ordering. The post-render
column `channel_refs` in `manifest.csv` is the source of truth for the
channel ↔ source-image mapping (pipe-separated, in channel order). Slots
beyond `len(channel_refs)` in the alpha_layers PNG are zero-filled.

Rendering is deterministic: same row in the manifest → byte-identical output.
Re-run with `--from-manifest` to re-render a (possibly edited) manifest.

Usage:
    uv run python -m data.generate_sequences \
        --fg-root backend/data/magick_dev \
        --bg-root backend/data/bg20k_dev \
        --output  backend/data/synth_dev \
        --count   10 \
        --seed    0

    # Restrict to specific MAGICK classes (requires predictions.csv from
    # data.classify_clip in <fg-root>):
    uv run python -m data.generate_sequences ... \
        --classes person,animal,plant
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

# Max per-object alpha layers packed into the RGB channels of a single
# `alpha_layers/<frame>.png`. Hard-capped at 3 to match the meeting decision
# (≤3 foregrounds per scene → fits in one PNG; would otherwise need a TIFF
# or a second sidecar PNG).
LAYER_CHANNELS = 3

# --------------------------------------------------------------------------- #
# Pose and homography                                                         #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Pose:
    """Foreground pose on the output frame.

    All fields are in normalized / degree units so they compose cleanly.
    tx, ty   — object center offset from frame center, in fractions of frame.
    scale    — object size as fraction of frame edge (1.0 ⇒ edge-to-edge).
    rot_deg  — in-plane rotation, degrees.
    tilt_x   — 3D rotation around horizontal axis, degrees (perspective).
    tilt_y   — 3D rotation around vertical axis, degrees.
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


def _ease_in_out_cubic(t: float) -> float:
    return 4.0 * t**3 if t < 0.5 else 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


def _ease_in_out_quint(t: float) -> float:
    return 16.0 * t**5 if t < 0.5 else 1.0 - ((-2.0 * t + 2.0) ** 5) / 2.0


# Pool of easing curves used to interpolate per-layer pose between start and
# end. All map [0, 1] -> [0, 1] with f(0) = 0 and f(1) = 1, monotonic, no
# overshoot. Insertion order = display order from easings.net (in / out /
# in-out within each intensity tier) and is what manifests record.
EASING_FNS: dict[str, Callable[[float], float]] = {
    "easeInSine": lambda t: 1.0 - math.cos(t * math.pi / 2.0),
    "easeOutSine": lambda t: math.sin(t * math.pi / 2.0),
    "easeInOutSine": lambda t: 0.5 * (1.0 - math.cos(math.pi * t)),
    "easeInCubic": lambda t: t**3,
    "easeOutCubic": lambda t: 1.0 - (1.0 - t) ** 3,
    "easeInOutCubic": _ease_in_out_cubic,
    "easeInQuint": lambda t: t**5,
    "easeOutQuint": lambda t: 1.0 - (1.0 - t) ** 5,
    "easeInOutQuint": _ease_in_out_quint,
}

EASING_NAMES_DEFAULT: tuple[str, ...] = tuple(EASING_FNS)


def ease_in_out(t: float) -> float:
    # Deprecated wrapper kept for one minor version; prefer EASING_FNS lookup.
    return EASING_FNS["easeInOutSine"](t)


# --------------------------------------------------------------------------- #
# Homography building                                                         #
# --------------------------------------------------------------------------- #


def _solve_homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Forward 3×3 homography mapping src (N,2) → dst (N,2). N must be 4."""
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
    """Where the object's 4 corners land on the output frame.

    Builds corners by: center on origin → perspective tilt → in-plane rot →
    scale → translate to (tx, ty) around frame center.
    """
    F = frame_size
    # Unit square corners centered on origin.
    corners = np.array(
        [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]],
        dtype=np.float64,
    )
    # 3D perspective tilt: lift corners to z = focal, rotate around X and Y,
    # project back. focal in units of half-edge — larger ⇒ milder perspective.
    focal = 1.8
    pts3d = np.column_stack([corners, np.full(4, focal)])
    a = math.radians(pose.tilt_x)
    b = math.radians(pose.tilt_y)
    rx = np.array(
        [[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]],
    )
    ry = np.array(
        [[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]],
    )
    pts3d = pts3d @ rx.T @ ry.T
    # Perspective project.
    pts2d = pts3d[:, :2] * (focal / pts3d[:, 2:3])

    # Scale to target object size in frame pixels.
    pts2d *= pose.scale * F

    # In-plane rotation around origin.
    theta = math.radians(pose.rot_deg)
    rot = np.array(
        [[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]],
    )
    pts2d = pts2d @ rot.T

    # Translate: (tx, ty) is center offset in fractions of frame; shift to
    # frame coordinates (top-left origin).
    cx = pose.tx * F + F / 2.0
    cy = pose.ty * F + F / 2.0
    return pts2d + np.array([cx, cy])


def build_fg_homography(pose: Pose, src_size: int, frame_size: int) -> np.ndarray:
    """Forward homography: source-image pixels → output-frame pixels."""
    src_corners = np.array(
        [[0, 0], [src_size, 0], [src_size, src_size], [0, src_size]],
        dtype=np.float64,
    )
    dst_corners = _fg_target_corners(pose, frame_size)
    return _solve_homography(src_corners, dst_corners)


def build_bg_homography(pose: Pose, src_size: int, frame_size: int) -> np.ndarray:
    """Forward homography for a background.

    Background is pre-resized to `src_size` (larger than frame, with margin).
    Pose.scale ≈ 1 and interpreted as zoom about frame center; translations and
    tilt are bounded so the warped image covers the frame.
    """
    F = frame_size
    # Unit frame corners centered on origin (output side).
    base = np.array(
        [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]],
        dtype=np.float64,
    )
    focal = 2.5  # milder perspective for BG
    pts3d = np.column_stack([base, np.full(4, focal)])
    a = math.radians(pose.tilt_x)
    b = math.radians(pose.tilt_y)
    rx = np.array(
        [[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]],
    )
    ry = np.array(
        [[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]],
    )
    pts3d = pts3d @ rx.T @ ry.T
    pts2d = pts3d[:, :2] * (focal / pts3d[:, 2:3])

    # Divide by scale: scale > 1 zooms in (samples a smaller area of the BG).
    pts2d *= F / pose.scale

    theta = math.radians(pose.rot_deg)
    rot = np.array(
        [[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]],
    )
    pts2d = pts2d @ rot.T

    # Translate by (tx, ty) fractions of frame, plus recenter onto bg source.
    cx = pose.tx * F + src_size / 2.0
    cy = pose.ty * F + src_size / 2.0
    src_region = pts2d + np.array([cx, cy])

    # Map that source region → output frame corners (0..F).
    dst_corners = np.array([[0, 0], [F, 0], [F, F], [0, F]], dtype=np.float64)
    return _solve_homography(src_region, dst_corners)


def warp_pillow(img: Image.Image, H: np.ndarray, out_size: int) -> Image.Image:
    """Apply forward homography H using Pillow's PERSPECTIVE transform.

    Pillow's transform takes the *inverse* mapping from output to source, so we
    invert H and pass the first 8 coefficients (normalized by [2,2]).
    """
    inv = np.linalg.inv(H)
    inv = inv / inv[2, 2]
    coeffs = tuple(inv.flatten()[:8])
    return img.transform(
        (out_size, out_size),
        Image.Transform.PERSPECTIVE,
        coeffs,
        resample=Image.Resampling.BILINEAR,
    )


# --------------------------------------------------------------------------- #
# Asset loading                                                               #
# --------------------------------------------------------------------------- #


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


def _load_page_id_labels(fg_root: Path) -> dict[str, str]:
    """Return {page_id: top_label} from <fg_root>/predictions.csv."""
    path = fg_root / "predictions.csv"
    if not path.exists():
        raise SystemExit(
            f"--classes requires {path}; run `data.classify_clip` on {fg_root} first.",
        )
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return {row["page_id"]: row["top_label"] for row in reader}


def list_foreground_refs(
    fg_root: Path,
    classes: list[str] | None = None,
) -> list[str]:
    """Return list of relative paths like '0L/0LZCNUeBHK.png' under images/.

    If `classes` is given, keep only foregrounds whose top_label (from
    predictions.csv) is in that set.
    """
    root = fg_root / "images"
    if not root.exists():
        raise FileNotFoundError(f"foreground images dir missing: {root}")
    refs = sorted(str(p.relative_to(root)) for p in root.rglob("*.png") if p.is_file())
    if not classes:
        return refs
    allowed = set(classes)
    labels = _load_page_id_labels(fg_root)
    return [r for r in refs if labels.get(Path(r).stem) in allowed]


def list_background_refs(bg_root: Path) -> list[str]:
    """Return list of relative paths like 'train/h_abc.jpg' under images/."""
    root = bg_root / "images"
    if not root.exists():
        raise FileNotFoundError(f"background images dir missing: {root}")
    refs: list[str] = []
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        refs.extend(str(p.relative_to(root)) for p in root.rglob(ext) if p.is_file())
    return sorted(refs)


# --------------------------------------------------------------------------- #
# Pose sampling                                                               #
# --------------------------------------------------------------------------- #


@dataclass
class SampleConfig:
    scale_min: float = 0.20
    scale_max: float = 0.80
    max_exit: float = 0.20
    max_rot: float = 25.0
    max_tilt: float = 15.0
    bg_pan: float = 0.10
    bg_zoom: float = 0.10
    bg_margin: float = 0.15  # pre-resize BG to frame * (1 + 2 * margin)
    easings: tuple[str, ...] = EASING_NAMES_DEFAULT


def _tx_bound(scale: float, max_exit: float) -> float:
    """Max absolute value for tx given scale and max_exit, clamped ≥ 0."""
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
    # BG scale > 1 means zoom in.
    return Pose(
        tx=rng.uniform(-cfg.bg_pan, cfg.bg_pan),
        ty=rng.uniform(-cfg.bg_pan, cfg.bg_pan),
        scale=rng.uniform(1.0, 1.0 + cfg.bg_zoom),
        rot_deg=rng.uniform(-cfg.max_tilt * 0.2, cfg.max_tilt * 0.2),
        tilt_x=rng.uniform(-cfg.max_tilt * 0.2, cfg.max_tilt * 0.2),
        tilt_y=rng.uniform(-cfg.max_tilt * 0.2, cfg.max_tilt * 0.2),
    )


# --------------------------------------------------------------------------- #
# Sequence specs & manifest                                                   #
# --------------------------------------------------------------------------- #


@dataclass
class SequenceSpec:
    seq_id: int
    seed: int
    n_frames: int
    size: int
    bg_ref: str  # e.g. 'train/h_abc.jpg'
    object_refs: list[str]  # input order; e.g. ['0L/0LZCNUeBHK.png', ...]
    # Post-render: source ref per alpha_layers channel, in paint order.
    # Empty until render_sequence has run.
    channel_refs: list[str] = field(default_factory=list)
    # Per-layer easing names; paint-order aligned with channel_refs.
    # When loaded from manifest these guard render_sequence's sampling so
    # `--from-manifest` reproduces the recorded scene.
    bg_easing: str = ""
    object_easings: list[str] = field(default_factory=list)


MANIFEST_FIELDS = (
    "seq_id",
    "seed",
    "n_frames",
    "size",
    "bg_ref",
    "object_refs",
    "channel_refs",
    "bg_easing",
    "object_easings",
)


def _bg_split(bg_ref: str) -> str:
    head, _, _ = bg_ref.partition("/")
    return head


def build_manifest(args: argparse.Namespace) -> list[SequenceSpec]:
    fg_refs = list_foreground_refs(args.fg_root, args.classes)
    bg_refs = list_background_refs(args.bg_root)
    if not fg_refs:
        if args.classes:
            raise SystemExit(
                f"no foregrounds under {args.fg_root}/images match classes {args.classes}",
            )
        raise SystemExit(f"no foregrounds found under {args.fg_root}/images")
    if not bg_refs:
        raise SystemExit(f"no backgrounds found under {args.bg_root}/images")

    specs: list[SequenceSpec] = []
    for i in range(args.count):
        seq_seed = args.seed + i
        rng = random.Random(seq_seed)
        n_obj = rng.randint(args.n_objects_min, args.n_objects_max)
        n_obj = min(n_obj, len(fg_refs))
        objs = rng.sample(fg_refs, n_obj)
        bg = rng.choice(bg_refs)
        specs.append(
            SequenceSpec(
                seq_id=i + 1,
                seed=seq_seed,
                n_frames=args.frames,
                size=args.size,
                bg_ref=bg,
                object_refs=objs,
            ),
        )
    return specs


def write_manifest(path: Path, specs: list[SequenceSpec]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(MANIFEST_FIELDS)
        for s in specs:
            writer.writerow(
                [
                    s.seq_id,
                    s.seed,
                    s.n_frames,
                    s.size,
                    s.bg_ref,
                    "|".join(s.object_refs),
                    "|".join(s.channel_refs),
                    s.bg_easing,
                    "|".join(s.object_easings),
                ],
            )


def read_manifest(path: Path) -> list[SequenceSpec]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        specs: list[SequenceSpec] = []
        for row in reader:
            object_refs = [r for r in row["object_refs"].split("|") if r]
            object_easings = [
                e for e in (row.get("object_easings") or "").split("|") if e
            ]
            # Legacy fallback: an old manifest with no easing columns must
            # re-render bit-identically. Fill with the cosine ease-in-out
            # under its new name so render_sequence's sampling guard skips.
            bg_easing = row.get("bg_easing") or "easeInOutSine"
            if not object_easings:
                object_easings = ["easeInOutSine"] * len(object_refs)
            specs.append(
                SequenceSpec(
                    seq_id=int(row["seq_id"]),
                    seed=int(row["seed"]),
                    n_frames=int(row["n_frames"]),
                    size=int(row["size"]),
                    bg_ref=row["bg_ref"],
                    object_refs=object_refs,
                    channel_refs=[
                        r for r in (row.get("channel_refs") or "").split("|") if r
                    ],
                    bg_easing=bg_easing,
                    object_easings=object_easings,
                ),
            )
    return specs


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #


@dataclass
class ObjectTrack:
    ref: str  # source ref relative to <fg-root>/images, e.g. '0L/0LZCNUeBHK.png'
    img: Image.Image  # RGBA, square source_size × source_size
    source_size: int
    depth: float  # z-order key; larger ⇒ farther (rendered first)
    pose_start: Pose
    pose_end: Pose
    easing: str = "easeInOutSine"


def prepare_background(path: Path, frame_size: int, margin: float) -> Image.Image:
    src_size = int(round(frame_size * (1.0 + 2.0 * margin)))
    img = Image.open(path).convert("RGB")
    return resize_shortest_side_and_center_crop(img, src_size)


def prepare_foreground(path: Path, src_size: int) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    return resize_shortest_side_and_center_crop(img, src_size)


def render_sequence(
    spec: SequenceSpec,
    fg_root: Path,
    bg_root: Path,
    out_dir: Path,
    cfg: SampleConfig,
) -> None:
    """Render one sequence and populate spec.channel_refs / spec.bg_easing /
    spec.object_easings (all paint-order aligned)."""
    # Pose RNG is derived from the seed but on a separate stream from the
    # asset-selection RNG used in build_manifest, so re-rendering a
    # hand-edited manifest (different assets, same seed) is deterministic.
    rng = random.Random(f"poses:{spec.seed}")

    frame_size = spec.size
    bg_img = prepare_background(
        bg_root / "images" / spec.bg_ref,
        frame_size,
        cfg.bg_margin,
    )
    bg_src_size = bg_img.size[0]

    objs: list[ObjectTrack] = []
    for ref in spec.object_refs:
        fg_img = prepare_foreground(fg_root / "images" / ref, frame_size)
        pose_start = sample_fg_pose(rng, cfg)
        pose_end = sample_fg_pose(rng, cfg)
        depth = rng.random()  # deeper = larger value, drawn first
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
    # Back-to-front painter order: farthest first (largest depth first).
    objs.sort(key=lambda o: -o.depth)
    if len(objs) > LAYER_CHANNELS:
        raise ValueError(
            f"sequence {spec.seq_id}: {len(objs)} objects > LAYER_CHANNELS="
            f"{LAYER_CHANNELS}; alpha_layers PNG can pack at most 3 layers.",
        )

    bg_start = sample_bg_pose(rng, cfg)
    bg_end = sample_bg_pose(rng, cfg)

    # Per-layer easing. Sample only when the spec doesn't already carry
    # values (loaded from a non-legacy manifest, or pre-populated by tests).
    # Sampling happens after all pose-determining draws so old seeds stay
    # bit-identical when --easings easeInOutSine is used.
    if not spec.bg_easing:
        spec.bg_easing = rng.choice(cfg.easings)
    if not spec.object_easings:
        # objs is in paint order (sorted by -depth); align easings to it.
        spec.object_easings = [rng.choice(cfg.easings) for _ in objs]
    for obj, name in zip(objs, spec.object_easings, strict=True):
        obj.easing = name
    bg_easing_fn = EASING_FNS[spec.bg_easing]

    aif_dir = out_dir / "all_in_focus"
    alpha_dir = out_dir / "alpha"
    layers_dir = out_dir / "alpha_layers"
    aif_dir.mkdir(parents=True, exist_ok=True)
    alpha_dir.mkdir(parents=True, exist_ok=True)
    layers_dir.mkdir(parents=True, exist_ok=True)

    digits = max(2, len(str(spec.n_frames)))

    for i in range(spec.n_frames):
        t = 0.0 if spec.n_frames == 1 else i / (spec.n_frames - 1)
        te_bg = bg_easing_fn(t)

        # Background.
        bg_pose = bg_start.lerp(bg_end, te_bg)
        H_bg = build_bg_homography(bg_pose, bg_src_size, frame_size)
        bg_warp = warp_pillow(bg_img, H_bg, frame_size)
        rgb = np.asarray(bg_warp, dtype=np.float32)  # (F, F, 3), 0..255
        alpha = np.zeros((frame_size, frame_size), dtype=np.float32)  # 0..1
        # Per-object alpha: channel index = paint order (0 = bottommost).
        # Slots beyond `len(objs)` stay zero.
        layers = np.zeros(
            (LAYER_CHANNELS, frame_size, frame_size),
            dtype=np.float32,
        )

        # Foregrounds, back-to-front.
        for ch, obj in enumerate(objs):
            te_obj = EASING_FNS[obj.easing](t)
            pose = obj.pose_start.lerp(obj.pose_end, te_obj)
            H_fg = build_fg_homography(pose, obj.source_size, frame_size)
            fg_warp = warp_pillow(obj.img, H_fg, frame_size)
            fg_arr = np.asarray(fg_warp, dtype=np.float32)  # (F, F, 4)
            fg_rgb = fg_arr[..., :3]
            fg_a = fg_arr[..., 3] / 255.0  # (F, F), 0..1
            a = fg_a[..., None]
            rgb = a * fg_rgb + (1.0 - a) * rgb
            alpha = np.maximum(alpha, fg_a)
            layers[ch] = fg_a

        frame_idx = i + 1
        name = f"{frame_idx:0{digits}d}.png"
        Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), mode="RGB").save(
            aif_dir / name,
            compress_level=6,
        )
        Image.fromarray(np.clip(alpha * 255.0, 0, 255).astype(np.uint8), mode="L").save(
            alpha_dir / name,
            compress_level=6,
        )
        # (F, F, 3) RGB PNG: R=ch0 alpha, G=ch1, B=ch2. Empty channels = 0.
        layers_rgb = np.transpose(
            np.clip(layers * 255.0, 0, 255).astype(np.uint8),
            (1, 2, 0),
        )
        Image.fromarray(layers_rgb, mode="RGB").save(
            layers_dir / name,
            compress_level=6,
        )

    spec.channel_refs = [obj.ref for obj in objs]


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fg-root", type=Path, default=Path("data/magick_dev"))
    parser.add_argument("--bg-root", type=Path, default=Path("data/bg20k_dev"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--frames", type=int, default=80)
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-objects-min", type=int, default=1)
    parser.add_argument("--n-objects-max", type=int, default=3)
    parser.add_argument("--scale-min", type=float, default=0.20)
    parser.add_argument("--scale-max", type=float, default=0.80)
    parser.add_argument("--max-exit", type=float, default=0.20)
    parser.add_argument("--max-rot", type=float, default=25.0)
    parser.add_argument("--max-tilt", type=float, default=15.0)
    parser.add_argument("--bg-pan", type=float, default=0.10)
    parser.add_argument("--bg-zoom", type=float, default=0.10)
    parser.add_argument(
        "--easings",
        type=lambda s: tuple(c.strip() for c in s.split(",") if c.strip()),
        default=EASING_NAMES_DEFAULT,
        help=(
            "Comma-separated subset of easing names to sample from per layer "
            "(background and each foreground). Default: all 9. Pass a single "
            "name to disable per-object variety (e.g. "
            "'--easings easeInOutSine' reproduces pre-change behavior)."
        ),
    )
    parser.add_argument(
        "--classes",
        type=lambda s: [c.strip() for c in s.split(",") if c.strip()],
        default=None,
        help="Comma-separated class labels to keep (e.g. 'person,animal'). "
        "Requires <fg-root>/predictions.csv from `data.classify_clip`.",
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Write the manifest and exit; skip rendering.",
    )
    parser.add_argument(
        "--from-manifest",
        type=Path,
        default=None,
        help="Render a (possibly hand-edited) manifest.csv instead of building one.",
    )
    return parser


def _validate_easings(names: tuple[str, ...]) -> None:
    if not names:
        raise SystemExit("--easings cannot be empty")
    unknown = [n for n in names if n not in EASING_FNS]
    if unknown:
        raise SystemExit(
            f"unknown easing(s): {unknown}; valid: {sorted(EASING_FNS)}",
        )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _validate_easings(tuple(args.easings))

    cfg = SampleConfig(
        scale_min=args.scale_min,
        scale_max=args.scale_max,
        max_exit=args.max_exit,
        max_rot=args.max_rot,
        max_tilt=args.max_tilt,
        bg_pan=args.bg_pan,
        bg_zoom=args.bg_zoom,
        easings=tuple(args.easings),
    )

    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "manifest.csv"

    if args.from_manifest is not None:
        specs = read_manifest(args.from_manifest)
        print(f"Loaded {len(specs)} sequence(s) from {args.from_manifest}")
    else:
        specs = build_manifest(args)
        write_manifest(manifest_path, specs)
        print(f"Wrote manifest: {manifest_path} ({len(specs)} sequence(s))")
        if args.manifest_only:
            return 0

    for spec in specs:
        seq_name = f"{spec.seq_id:04d}"
        out_dir = args.output / "sequences" / seq_name
        print(
            f"  {seq_name}  seed={spec.seed}  "
            f"bg={_bg_split(spec.bg_ref)}  n_obj={len(spec.object_refs)}  "
            f"frames={spec.n_frames}",
        )
        render_sequence(
            spec,
            args.fg_root,
            args.bg_root,
            out_dir,
            cfg,
        )
        # Rewrite manifest after each sequence so channel_refs are durable
        # against Ctrl-C mid-batch.
        write_manifest(manifest_path, specs)

    print(f"\nDone. Sequences in {args.output / 'sequences'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
