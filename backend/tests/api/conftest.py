from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from fixture_library import BG_SIZE, ESTIMATOR, FG_SIZE, build_library


@dataclass(frozen=True)
class LibraryFacts:
    """What the fixture library was built with, so assertions do not hardcode it twice."""

    fg_size: int = FG_SIZE
    bg_size: int = BG_SIZE
    estimator: str = ESTIMATOR


@pytest.fixture
def facts() -> LibraryFacts:
    return LibraryFacts()


@pytest.fixture
def make_library(tmp_path: Path) -> Callable[..., Path]:
    """Build a library of a given shape. See `fixture_library` for why it is real."""

    def _make(
        name: str = "library",
        foregrounds: tuple[str, ...] = ("fg_a", "fg_b"),
        backgrounds: tuple[str, ...] = ("bg_a", "bg_b"),
        estimator: str = ESTIMATOR,
    ) -> Path:
        return build_library(tmp_path / name, foregrounds, backgrounds, estimator)

    return _make


@pytest.fixture
def library(make_library: Callable[..., Path]) -> Path:
    return make_library()
