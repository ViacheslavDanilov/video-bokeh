"""On-disk layout and I/O for the precomputed artifact library.

    <library>/
    ├── foregrounds/<id>/{rgb.png (RGBA), alpha.png (L), depth.tif (float32)}
    └── backgrounds/<id>/{rgb.png (RGB), depth.tif (float32)}

Depth is stored as float32 .tif, larger = closer (disparity convention).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

FOREGROUNDS = "foregrounds"
BACKGROUNDS = "backgrounds"


@dataclass
class ForegroundAsset:
    asset_id: str
    rgb: Image.Image  # RGBA
    alpha: np.ndarray  # (H, W) float32 in [0, 1]
    depth: np.ndarray  # (H, W) float32, propagated full-frame disparity


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
) -> None:
    out = library_root / FOREGROUNDS / asset_id
    out.mkdir(parents=True, exist_ok=True)
    rgb.convert("RGBA").save(out / "rgb.png", compress_level=6)
    a = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    Image.fromarray(a, mode="L").save(out / "alpha.png", compress_level=6)
    tifffile.imwrite(out / "depth.tif", depth.astype(np.float32))


def write_background(
    library_root: Path,
    asset_id: str,
    rgb: Image.Image,
    depth: np.ndarray,
) -> None:
    out = library_root / BACKGROUNDS / asset_id
    out.mkdir(parents=True, exist_ok=True)
    rgb.convert("RGB").save(out / "rgb.png", compress_level=6)
    tifffile.imwrite(out / "depth.tif", depth.astype(np.float32))


def load_foreground(library_root: Path, asset_id: str) -> ForegroundAsset:
    base = library_root / FOREGROUNDS / asset_id
    rgb = Image.open(base / "rgb.png").convert("RGBA")
    alpha = np.asarray(Image.open(base / "alpha.png").convert("L"), dtype=np.float32)
    alpha /= 255.0
    depth = tifffile.imread(base / "depth.tif").astype(np.float32)
    return ForegroundAsset(asset_id, rgb, alpha, depth)


def load_background(library_root: Path, asset_id: str) -> BackgroundAsset:
    base = library_root / BACKGROUNDS / asset_id
    rgb = Image.open(base / "rgb.png").convert("RGB")
    depth = tifffile.imread(base / "depth.tif").astype(np.float32)
    return BackgroundAsset(asset_id, rgb, depth)
