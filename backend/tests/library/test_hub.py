"""A library packed into shards for Hugging Face, and fetched back into the layout Stage B reads."""

from __future__ import annotations

import json
import sys
import tarfile
from pathlib import Path

import pytest

# The fixture library lives with the API tests, which use it too.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from fixture_library import build_library  # noqa: E402

from video_bokeh.core._library import list_backgrounds, list_foregrounds  # noqa: E402
from video_bokeh.library import hub  # noqa: E402


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = build_library(
        tmp_path / "library", ("fg_a", "fg_b", "fg_c"), ("bg_a", "bg_b")
    )
    # What Stage A keeps for inspection and Stage B never reads.
    (root / "foregrounds" / "fg_a" / "depth_raw.png").write_bytes(b"raw")
    (root / "foregrounds" / "fg_a" / "depth_input.png").write_bytes(b"input")
    return root


def _files(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }


def test_fetching_a_packed_library_gives_back_what_stage_b_reads(
    library: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub.pack(library, tmp_path / "packed")
    calls = []

    def snapshot_download(**kwargs: object) -> str:
        calls.append(kwargs)
        return str(tmp_path / "packed")

    monkeypatch.setattr("huggingface_hub.snapshot_download", snapshot_download)
    fetched = hub.fetch("someone/some-library", tmp_path / "fetched")

    assert calls[0]["repo_id"] == "someone/some-library"
    assert calls[0]["repo_type"] == "dataset"
    expected = {
        name: data
        for name, data in _files(library).items()
        if not name.endswith(("depth_raw.png", "depth_input.png"))
    }
    assert _files(fetched) == expected
    assert list_foregrounds(fetched) == ["fg_a", "fg_b", "fg_c"]
    assert list_backgrounds(fetched) == ["bg_a", "bg_b"]


def test_a_shard_closes_near_its_size_and_never_splits_an_item(
    library: Path,
    tmp_path: Path,
) -> None:
    hub.pack(library, tmp_path / "packed", shard_bytes=1)
    shards = sorted((tmp_path / "packed" / "foregrounds").glob("*.tar"))
    assert len(shards) == 3  # every item overflows a 1-byte shard, so one item each
    for shard in shards:
        with tarfile.open(shard) as tar:
            items = {Path(name).parts[1] for name in tar.getnames()}
        assert len(items) == 1


def test_the_package_carries_its_card_and_its_counts(
    library: Path, tmp_path: Path
) -> None:
    hub.pack(library, tmp_path / "packed")
    index = json.loads((tmp_path / "packed" / "index.json").read_text())
    assert index["foregrounds"]["items"] == 3
    assert index["backgrounds"]["items"] == 2
    card = (tmp_path / "packed" / "README.md").read_text()
    assert "license: cc-by-nc-4.0" in card
    assert "3 foregrounds" in card and "2 backgrounds" in card


def test_packing_refuses_a_folder_that_is_no_library(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="foregrounds"):
        hub.pack(tmp_path, tmp_path / "packed")
