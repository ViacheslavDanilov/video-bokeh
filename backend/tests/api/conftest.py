from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from video_bokeh.core._library import write_background, write_foreground
from video_bokeh.core._metadata import write_asset_metadata

_FG_SIZE = 64
# Oversized, the way Stage A stores backgrounds, so Stage B's warp never samples
# past the source edge and leaves black holes in the frame.
_BG_SIZE = 192
_ESTIMATOR = "da2-small"


@dataclass(frozen=True)
class LibraryFacts:
    """What the fixture library was built with, so assertions do not hardcode it twice."""

    fg_size: int = _FG_SIZE
    bg_size: int = _BG_SIZE
    estimator: str = _ESTIMATOR


def _object_alpha(size: int) -> np.ndarray:
    """A centered square, so the asset has an inside and an outside like a real cut-out."""
    alpha = np.zeros((size, size), dtype=np.float32)
    lo, hi = size // 4, size - size // 4
    alpha[lo:hi, lo:hi] = 1.0
    return alpha


def _gradient(size: int, lo: float, hi: float) -> np.ndarray:
    return np.tile(np.linspace(lo, hi, size, dtype=np.float32), (size, 1))


def _build(
    root: Path,
    foregrounds: tuple[str, ...],
    backgrounds: tuple[str, ...],
) -> Path:
    for i, asset_id in enumerate(foregrounds):
        write_foreground(
            root,
            asset_id,
            Image.new("RGBA", (_FG_SIZE, _FG_SIZE), (20 + 40 * i, 90, 160, 255)),
            _object_alpha(_FG_SIZE),
            _gradient(_FG_SIZE, 0.2, 0.9),
        )
        write_asset_metadata(
            root / "foregrounds" / asset_id,
            {"estimator": _ESTIMATOR, "source_ref": f"xx/{asset_id}.png"},
        )
    for i, asset_id in enumerate(backgrounds):
        write_background(
            root,
            asset_id,
            Image.new("RGB", (_BG_SIZE, _BG_SIZE), (200, 30 + 20 * i, 40)),
            _gradient(_BG_SIZE, 0.0, 1.0),
        )
    return root


@pytest.fixture
def facts() -> LibraryFacts:
    return LibraryFacts()


@pytest.fixture
def make_library(tmp_path: Path) -> Callable[..., Path]:
    """Build a library of a given shape.

    Real assets rather than a mock: scene generation reads them through the same
    loaders the pipeline uses, so a fake would only prove the fake behaves like the
    fake.
    """

    def _make(
        name: str = "library",
        foregrounds: tuple[str, ...] = ("fg_a", "fg_b"),
        backgrounds: tuple[str, ...] = ("bg_a", "bg_b"),
    ) -> Path:
        return _build(tmp_path / name, foregrounds, backgrounds)

    return _make


@pytest.fixture
def library(make_library: Callable[..., Path]) -> Path:
    return make_library()
