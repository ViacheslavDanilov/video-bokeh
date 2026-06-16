"""On-disk layout and I/O for the precomputed artifact library.

    <library>/
    ├── foregrounds/<id>/{rgb.png (RGBA), alpha.png (L), depth.png (uint16),
    │                     depth_raw.png (uint16, optional)}
    └── backgrounds/<id>/{rgb.png (RGB), depth.png (uint16)}

Depth is stored as a uint16 PNG, larger = closer (disparity convention). Each
map is min/max-normalized to the full 16-bit range on write and returned as a
float32 array in [0, 1] on read. The absolute disparity scale is intentionally
dropped: the compositor percentile-stretches each depth map into a band, so only
the relative structure matters and 16 bits preserves it without visible banding.

``depth.png`` is the propagated full-frame map consumed by Stage B.
``depth_raw.png`` is the estimator's untouched output before propagation, saved
only as a diagnostic (raw-vs-propagated comparison); it is optional, so older
libraries without it load with ``raw_depth=None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

FOREGROUNDS = "foregrounds"
BACKGROUNDS = "backgrounds"
_U16_MAX = 65535


def _write_depth_png(path: Path, depth: np.ndarray) -> None:
    """Min/max-normalize a float depth map to uint16 and save as PNG."""
    arr = np.asarray(depth, dtype=np.float32)
    lo = float(arr.min())
    hi = float(arr.max())
    span = hi - lo
    if span <= 1e-12:
        normed = np.zeros_like(arr)
    else:
        normed = (arr - lo) / span
    quantized = (normed * _U16_MAX).round().astype(np.uint16)
    # Pillow infers mode 'I;16' from the uint16 dtype; passing mode= is deprecated.
    Image.fromarray(quantized).save(path, compress_level=6)


def _read_depth_png(path: Path) -> np.ndarray:
    """Read a uint16 depth PNG back as float32 in [0, 1]."""
    arr = np.asarray(Image.open(path)).astype(np.float32)
    return arr / _U16_MAX


@dataclass
class ForegroundAsset:
    asset_id: str
    rgb: Image.Image  # RGBA
    alpha: np.ndarray  # (H, W) float32 in [0, 1]
    depth: np.ndarray  # (H, W) float32, propagated full-frame disparity
    raw_depth: np.ndarray | None = None  # (H, W) float32, estimator output (diagnostic)


@dataclass
class BackgroundAsset:
    asset_id: str
    rgb: Image.Image  # RGB
    depth: np.ndarray  # (H, W) float32 disparity


def _ids(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def list_foregrounds(library_root: Path) -> list[str]:
    return _ids(library_root / FOREGROUNDS)


def list_backgrounds(library_root: Path) -> list[str]:
    return _ids(library_root / BACKGROUNDS)


def write_foreground(
    library_root: Path,
    asset_id: str,
    rgb: Image.Image,
    alpha: np.ndarray,
    depth: np.ndarray,
    raw_depth: np.ndarray | None = None,
) -> None:
    out = library_root / FOREGROUNDS / asset_id
    out.mkdir(parents=True, exist_ok=True)
    rgb.convert("RGBA").save(out / "rgb.png", compress_level=6)
    a = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    Image.fromarray(a, mode="L").save(out / "alpha.png", compress_level=6)
    _write_depth_png(out / "depth.png", depth)
    if raw_depth is not None:
        _write_depth_png(out / "depth_raw.png", raw_depth)


def write_background(
    library_root: Path,
    asset_id: str,
    rgb: Image.Image,
    depth: np.ndarray,
) -> None:
    out = library_root / BACKGROUNDS / asset_id
    out.mkdir(parents=True, exist_ok=True)
    rgb.convert("RGB").save(out / "rgb.png", compress_level=6)
    _write_depth_png(out / "depth.png", depth)


def load_foreground(library_root: Path, asset_id: str) -> ForegroundAsset:
    base = library_root / FOREGROUNDS / asset_id
    rgb = Image.open(base / "rgb.png").convert("RGBA")
    alpha = np.asarray(Image.open(base / "alpha.png").convert("L"), dtype=np.float32)
    alpha /= 255.0
    depth = _read_depth_png(base / "depth.png")
    raw_path = base / "depth_raw.png"
    raw_depth = _read_depth_png(raw_path) if raw_path.exists() else None
    return ForegroundAsset(asset_id, rgb, alpha, depth, raw_depth=raw_depth)


def load_background(library_root: Path, asset_id: str) -> BackgroundAsset:
    base = library_root / BACKGROUNDS / asset_id
    rgb = Image.open(base / "rgb.png").convert("RGB")
    depth = _read_depth_png(base / "depth.png")
    return BackgroundAsset(asset_id, rgb, depth)
