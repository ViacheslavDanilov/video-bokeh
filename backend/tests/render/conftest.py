from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The fixture library lives with the API tests, which use it too; pytest puts only this
# directory on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from fixture_library import build_library  # noqa: E402


@pytest.fixture
def library(tmp_path: Path) -> Path:
    return build_library(tmp_path / "library", ("fg_a", "fg_b"), ("bg_a", "bg_b"))
