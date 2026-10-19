"""The balanced test set: plain sequences, and hard-edge ones kept by rule from fixed pools."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "comparison"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import numpy as np  # noqa: E402
from balanced_test_set import build, pools, read_objects  # noqa: E402
from fixture_library import FG_SIZE, _gradient, _object_alpha  # noqa: E402
from PIL import Image  # noqa: E402

from video_bokeh.core._library import write_background, write_foreground  # noqa: E402

BG_SIZE = 256
#: Each object's gray level and category: light edges, dark ones, and a middling one that
#: counts as light, but shows little against a dark background.
OBJECTS = {
    "hair_light": (230, "hair"),
    "hair_mid": (128, "hair"),
    "hair_dark": (20, "hair"),
    "fire_a": (90, "fire"),  # fire goes on a dark background, though its edge is dark
    "smoke_a": (200, "smoke"),
    "fine_a": (230, "fine"),
}
#: A fire object with a light edge, for a test that wants every category to show.
FIRE_LIGHT = 230
#: Each background's gray levels: noise between the two, or one flat level.
BACKGROUNDS = {
    "bg_dark": (0, 50),
    "bg_light": (205, 255),
    "bg_mid": (100, 150),  # detailed, but neither dark nor light
    "bg_flat": (20, 20),  # dark, but flat
}


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    levels = {asset: level for asset, (level, _) in OBJECTS.items()}
    for asset, level in (levels | {"fire_light": FIRE_LIGHT}).items():
        write_foreground(
            root,
            asset,
            Image.new("RGBA", (FG_SIZE, FG_SIZE), (level, level, level, 255)),
            _object_alpha(FG_SIZE),
            _gradient(FG_SIZE, 0.2, 0.9, False),
        )
    rng = np.random.default_rng(0)
    for asset, (lo, hi) in BACKGROUNDS.items():
        rgb = rng.integers(lo, hi + 1, (BG_SIZE, BG_SIZE, 3), np.uint8)
        ramp = _gradient(BG_SIZE, 0.0, 1.0, False)
        write_background(root, asset, Image.fromarray(rgb), ramp)
    return root


@pytest.fixture
def objects(tmp_path: Path) -> Path:
    path = tmp_path / "objects.txt"
    lines = [f"{asset} {category}" for asset, (_, category) in OBJECTS.items()]
    path.write_text("# a comment\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _build(library: Path, out: Path, objects: Path, **kwargs) -> list[dict[str, str]]:
    settings = {
        "objects": objects,
        "frames": 2,
        "size": 128,
        "plain_from": 0,
        "plain_count": 2,
        "hard_from": {"hair": 100, "fire": 200, "smoke": 300, "fine": 400},
        "hard_count": 1,
    }
    return build(library, out, **(settings | kwargs))


def test_light_edges_go_on_dark_backgrounds_and_dark_on_light(
    library: Path, objects: Path
) -> None:
    assert pools(library, read_objects(objects)) == {
        "hair": [
            ("dark", ["hair_light", "hair_mid"], ["bg_dark"]),
            ("light", ["hair_dark"], ["bg_light"]),
        ],
        "fire": [("dark", ["fire_a"], ["bg_dark"])],
        "smoke": [("dark", ["smoke_a"], ["bg_dark"])],
        "fine": [("dark", ["fine_a"], ["bg_dark"])],
    }


def test_writes_plain_and_hard_sequences_with_their_subsets(
    library: Path, objects: Path, tmp_path: Path
) -> None:
    out = tmp_path / "test_set"
    selection = _build(library, out, objects, hard_count=2)

    names = [row["name"] for row in selection]
    assert names == [
        "plain-01", "plain-02", "hair-01", "hair-02", "fire-01", "fire-02",
        "smoke-01", "smoke-02", "fine-01", "fine-02",
    ]  # fmt: skip
    assert _rows(out / "selection.csv") == selection
    assert sorted(p.name for p in (out / "sequences").iterdir()) == sorted(names)
    manifest = _rows(out / "manifest.csv")
    assert [(r["seq_id"], r["seed"]) for r in manifest] == [
        (row["name"], row["seed"]) for row in selection
    ]
    assert {r["seq_id"] for r in _rows(out / "objects.csv")} == set(names)
    for row in selection:
        group = "plain" if row["name"].startswith("plain") else "hard"
        assert row["group"] == group
        if group == "plain":
            assert row["category"] == "any"
            assert row["background"] != "bg_flat"
            continue
        assert row["category"] == row["name"].split("-")[0]
        assert OBJECTS[row["focus_fg"]][1] == row["category"]
        assert set(row["objects"].split(";")) <= {
            a for a, (_, c) in OBJECTS.items() if c == row["category"]
        }
        light_edge = row["focus_fg"] != "hair_dark"
        assert row["side"] == ("dark" if light_edge else "light")
        assert row["background"] == f"bg_{row['side']}"
        assert float(row["contrast"]) >= 0.15
        assert float(row["share"]) >= 0.01
    seeds = [int(row["seed"]) for row in selection if row["category"] == "hair"]
    assert {seed % 2 for seed in seeds} == {
        0,
        1,
    }  # both hair pools, by the seed's parity
    for subset, members in (
        ("plain", names[:2]),
        ("hard", sorted(names[2:])),
        ("hair", ["hair-01", "hair-02"]),
        ("smoke", ["smoke-01", "smoke-02"]),
    ):
        linked = sorted((out / subset / "sequences").iterdir())
        assert [p.name for p in linked] == members
        assert all(p.is_symlink() for p in linked)
        assert linked[0].resolve() == (out / "sequences" / members[0]).resolve()
    assert not (out / ".staging").exists()
    assert not (out / ".pool").exists()


def test_skips_an_edge_with_little_contrast(
    library: Path, objects: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "test_set"
    # The dark fire object would show too little against a dark background as well.
    objects.write_text(
        objects.read_text(encoding="utf-8").replace("fire_a", "fire_light"),
        encoding="utf-8",
    )
    selection = _build(
        library,
        out,
        objects,
        plain_count=0,
        hard_count=4,
        min_contrast=0.6,
        max_focus=4,
    )
    hair = [row for row in selection if row["category"] == "hair"]
    assert len(hair) == 4
    assert "hair_mid" not in {row["focus_fg"] for row in hair}
    assert "contrast" in capsys.readouterr().out  # a candidate was skipped for it


def test_stops_when_every_object_has_been_in_focus_enough(
    library: Path, objects: Path, tmp_path: Path
) -> None:
    out = tmp_path / "test_set"
    with pytest.raises(
        SystemExit, match="fire: every object has been in focus as often as allowed"
    ):
        _build(library, out, objects, plain_count=0, hard_count=2, max_focus=1)


def test_refuses_a_folder_that_is_not_empty(
    library: Path, objects: Path, tmp_path: Path
) -> None:
    out = tmp_path / "test_set"
    (out / "sequences").mkdir(parents=True)
    with pytest.raises(SystemExit, match="not empty"):
        _build(library, out, objects)
