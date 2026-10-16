"""The comparison's test set: named sequences in one root, and a night root linking to its own."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "comparison"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import numpy as np  # noqa: E402
from fixture_library import BG_SIZE, build_library  # noqa: E402
from PIL import Image  # noqa: E402
from test_set import build  # noqa: E402

from video_bokeh.core._library import write_background  # noqa: E402


@pytest.fixture
def library(tmp_path: Path) -> Path:
    return build_library(tmp_path / "library", ("fg_a", "fg_b"), ("bg_a", "bg_b"))


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_writes_named_sequences_and_a_night_root(library: Path, tmp_path: Path) -> None:
    out = tmp_path / "test_set"
    seeds = build(
        library,
        out,
        frames=2,
        size=32,
        any_from=0,
        any_count=2,
        night_seeds=(7,),
        min_detail=0,
    )

    assert seeds == {"any-01": 0, "any-02": 1, "night-01": 7}
    names = sorted(p.name for p in (out / "sequences").iterdir())
    assert names == ["any-01", "any-02", "night-01"]
    for name in names:
        seq = out / "sequences" / name
        assert (seq / "bokeh" / "focus.json").is_file()
        assert (seq / "layers").is_dir()
    manifest = _rows(out / "manifest.csv")
    assert [(r["seq_id"], int(r["seed"])) for r in manifest] == list(seeds.items())
    assert {r["seq_id"] for r in _rows(out / "objects.csv")} == set(names)
    linked = out / "night" / "sequences" / "night-01"
    assert linked.is_symlink()
    assert linked.resolve() == (out / "sequences" / "night-01").resolve()
    assert not (out / ".staging").exists()


def test_refuses_a_folder_that_is_not_empty(library: Path, tmp_path: Path) -> None:
    out = tmp_path / "test_set"
    out.mkdir()
    (out / "sequences").mkdir()  # as a run that stopped partway leaves it
    with pytest.raises(SystemExit):
        build(library, out, frames=2, size=32, any_count=1, night_seeds=())


def test_skips_seeds_whose_background_is_flat(library: Path, tmp_path: Path) -> None:
    noise = np.random.default_rng(0).integers(0, 256, (BG_SIZE, BG_SIZE, 3), np.uint8)
    ramp = np.tile(np.linspace(0, 1, BG_SIZE, dtype=np.float32), (BG_SIZE, 1))
    write_background(library, "bg_noise", Image.fromarray(noise), ramp)
    out = tmp_path / "test_set"
    build(library, out, frames=2, size=32, any_from=0, any_count=3, night_seeds=())
    backgrounds = [r["background"] for r in _rows(out / "manifest.csv")]
    assert backgrounds == ["bg_noise"] * 3  # the fixture's own backgrounds are flat
