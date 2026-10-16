"""The comparison's test set: named sequences in one root, and a night root linking to its own."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "comparison"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from fixture_library import build_library  # noqa: E402
from test_set import build  # noqa: E402


@pytest.fixture
def library(tmp_path: Path) -> Path:
    return build_library(tmp_path / "library", ("fg_a", "fg_b"), ("bg_a", "bg_b"))


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_writes_named_sequences_and_a_night_root(library: Path, tmp_path: Path) -> None:
    out = tmp_path / "test_set"
    seeds = build(
        library, out, frames=2, size=32, any_from=0, any_count=2, night_seeds=(7,)
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


def test_refuses_a_root_that_already_holds_one(library: Path, tmp_path: Path) -> None:
    out = tmp_path / "test_set"
    out.mkdir()
    (out / "manifest.csv").write_text("seq_id\n")
    with pytest.raises(SystemExit):
        build(library, out, frames=2, size=32, any_count=1, night_seeds=())
