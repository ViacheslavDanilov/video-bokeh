"""A tiny library of real assets, for the API tests and the browser smoke test.

Real files rather than a mock: sequence generation reads them through the same loaders the
pipeline uses, so a fake would only prove the fake behaves like the fake. No depth
estimator is involved -- the disparity maps are gradients -- so building one takes
milliseconds.

Run as a script to build one on disk:

    uv run python tests/api/fixture_library.py <library-root> [<depth estimator>]

The depth estimator is only a name here, so this stays free of torch: CI's browser job
installs the ``api`` extra alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

from video_bokeh.core._library import write_background, write_foreground
from video_bokeh.core._metadata import write_asset_metadata

FG_SIZE = 64
# Oversized, the way Stage A stores backgrounds, so Stage B's warp never samples past
# the source edge and leaves black holes in the frame.
BG_SIZE = 192
ESTIMATOR = "da2-small"


def _object_alpha(size: int) -> np.ndarray:
    """A centered square, so the asset has an inside and an outside like a real cut-out."""
    alpha = np.zeros((size, size), dtype=np.float32)
    lo, hi = size // 4, size - size // 4
    alpha[lo:hi, lo:hi] = 1.0
    return alpha


def _gradient(size: int, lo: float, hi: float, flip: bool) -> np.ndarray:
    ramp = np.linspace(lo, hi, size, dtype=np.float32)
    return np.tile(ramp[::-1] if flip else ramp, (size, 1))


def build_library(
    root: Path,
    foregrounds: tuple[str, ...],
    backgrounds: tuple[str, ...],
    estimator: str = ESTIMATOR,
) -> Path:
    # Any other estimator sees the disparity the other way round, so two libraries built
    # from the same assets differ in disparity and in nothing else -- which is what
    # comparing depth estimators means.
    flip = estimator != ESTIMATOR
    for i, asset_id in enumerate(foregrounds):
        write_foreground(
            root,
            asset_id,
            Image.new("RGBA", (FG_SIZE, FG_SIZE), (20 + 40 * i, 90, 160, 255)),
            _object_alpha(FG_SIZE),
            _gradient(FG_SIZE, 0.2, 0.9, flip),
        )
        write_asset_metadata(
            root / "foregrounds" / asset_id,
            {"estimator": estimator, "source_ref": f"xx/{asset_id}.png"},
        )
    for i, asset_id in enumerate(backgrounds):
        write_background(
            root,
            asset_id,
            Image.new("RGB", (BG_SIZE, BG_SIZE), (200, 30 + 20 * i, 40)),
            _gradient(BG_SIZE, 0.0, 1.0, flip),
        )
    return root


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit("usage: fixture_library.py <library-root> [<depth estimator>]")
    build_library(
        Path(sys.argv[1]),
        ("fg_a", "fg_b"),
        ("bg_a", "bg_b"),
        *sys.argv[2:],
    )
