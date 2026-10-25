"""The writer draws a run's assets from one split, train unless it is told otherwise."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from video_bokeh.core._library import write_background, write_foreground
from video_bokeh.core._split import listed_test_foregrounds
from video_bokeh.scenes.generate import generate_dataset, main

TEST_FG = sorted(listed_test_foregrounds())[:2]
TRAIN_FG = ["fg_a", "fg_b"]


@pytest.fixture
def library(tmp_path: Path) -> Path:
    """Two foregrounds and one background in each split."""
    root = tmp_path / "library"
    rgba = np.zeros((32, 32, 4), dtype=np.uint8)
    rgba[12:20, 12:20] = 255
    for i, asset_id in enumerate(TRAIN_FG + TEST_FG):
        write_foreground(
            root,
            asset_id,
            Image.fromarray(rgba, "RGBA"),
            rgba[..., 3] / 255.0,
            np.full((32, 32), 0.6 + 0.1 * i, dtype=np.float32),
        )
    for asset_id in ("train__h_bg", "testval__h_bg"):
        write_background(
            root,
            asset_id,
            Image.new("RGB", (48, 48), (30, 30, 30)),
            np.full((48, 48), 0.1, dtype=np.float32),
        )
    return root


def _assets(out: Path) -> tuple[set[str], set[str]]:
    """The foregrounds and the backgrounds a written run used."""
    with (out / "objects.csv").open(encoding="utf-8") as f:
        foregrounds = {row["foreground"] for row in csv.DictReader(f)}
    with (out / "manifest.csv").open(encoding="utf-8") as f:
        backgrounds = {row["background"] for row in csv.DictReader(f)}
    return foregrounds, backgrounds


def test_a_run_draws_train_assets_by_default(library: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    generate_dataset(library, out, 6, 2, 32, seed=0, n_objects_max=2)
    assert _assets(out) == (set(TRAIN_FG), {"train__h_bg"})


def test_the_test_split_draws_test_assets_alone(library: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    main(
        [
            "--library-root",
            str(library),
            "--output",
            str(out),
            "--count",
            "6",
            "--frames",
            "2",
            "--size",
            "32",
            "--n-objects-max",
            "2",
            "--split",
            "test",
        ],
    )
    assert _assets(out) == (set(TEST_FG), {"testval__h_bg"})
    assert json.loads((out / "run.json").read_text())["flags"]["split"] == "test"


def test_all_draws_from_both(library: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    generate_dataset(library, out, 12, 2, 32, seed=0, n_objects_max=2, split="all")
    foregrounds, backgrounds = _assets(out)
    assert foregrounds & set(TRAIN_FG) and foregrounds & set(TEST_FG)
    assert backgrounds == {"train__h_bg", "testval__h_bg"}


def test_a_split_without_assets_is_named(tmp_path: Path, library: Path) -> None:
    for asset_id in TEST_FG:
        for f in (library / "foregrounds" / asset_id).iterdir():
            f.unlink()
        (library / "foregrounds" / asset_id).rmdir()
    with pytest.raises(SystemExit, match="has no test foregrounds/backgrounds"):
        generate_dataset(library, tmp_path / "out", 1, 2, 32, seed=0, split="test")
