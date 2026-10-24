"""A library packed into shards for Hugging Face, and fetched back into the layout Stage B reads."""

from __future__ import annotations

import json
import shutil
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
        tmp_path / "library",
        ("fg_a", "fg_b", "fg_c"),
        ("bg_a", "bg_b"),
        estimator="da2-large",
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


def _hub(monkeypatch: pytest.MonkeyPatch, packed: Path) -> list[str]:
    """Serve ``packed`` as a dataset repository; return the files downloaded from it."""
    downloaded: list[str] = []

    def hf_hub_download(**kwargs: str) -> str:
        assert kwargs["repo_type"] == "dataset"
        downloaded.append(kwargs["filename"])
        target = Path(kwargs["local_dir"]) / kwargs["filename"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(packed / kwargs["filename"], target)
        return str(target)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", hf_hub_download)
    return downloaded


def test_fetching_a_packed_library_gives_back_what_stage_b_reads(
    library: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub.pack(library, tmp_path / "packed")
    _hub(monkeypatch, tmp_path / "packed")
    fetched = hub.fetch("someone/some-library", tmp_path / "fetched")

    expected = {
        name: data
        for name, data in _files(library).items()
        if not name.endswith(("depth_raw.png", "depth_input.png"))
    }
    got = {k: v for k, v in _files(fetched).items() if not k.startswith(".fetched/")}
    assert got == expected
    assert list_foregrounds(fetched) == ["fg_a", "fg_b", "fg_c"]
    assert list_backgrounds(fetched) == ["bg_a", "bg_b"]
    assert not list(fetched.glob("tmp*"))  # each shard is deleted once unpacked


def test_fetching_again_downloads_only_the_shards_added_since(
    library: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packed = tmp_path / "packed"
    index = hub.pack(library, packed, shard_bytes=1)
    full = (packed / "index.json").read_text()
    # A repository holding the first foreground shard and every background shard so far.
    first = dict(index)
    first["foregrounds"] = {
        **index["foregrounds"],
        "shards": index["foregrounds"]["shards"][:1],
    }
    (packed / "index.json").write_text(json.dumps(first))
    downloaded = _hub(monkeypatch, packed)
    hub.fetch("someone/some-library", tmp_path / "fetched")
    assert list_foregrounds(tmp_path / "fetched") == ["fg_a"]

    (packed / "index.json").write_text(full)
    downloaded.clear()
    hub.fetch("someone/some-library", tmp_path / "fetched")
    assert downloaded == [
        "index.json",
        "foregrounds/foregrounds-00001.tar",
        "foregrounds/foregrounds-00002.tar",
    ]
    assert list_foregrounds(tmp_path / "fetched") == ["fg_a", "fg_b", "fg_c"]


def test_a_shard_closes_near_its_size_and_never_splits_an_item(
    library: Path,
    tmp_path: Path,
) -> None:
    index = hub.pack(library, tmp_path / "packed", shard_bytes=1)
    assert [s["items"] for s in index["foregrounds"]["shards"]] == [1, 1, 1]
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
    assert "license: cc-by-nc-4.0" in card and "viewer: false" in card
    assert "3 foregrounds" in card and "2 backgrounds" in card


def test_packing_refuses_a_folder_that_is_no_library(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="foregrounds"):
        hub.pack(tmp_path, tmp_path / "packed")


def test_packing_refuses_a_used_folder_and_another_estimator(
    library: Path,
    tmp_path: Path,
) -> None:
    (tmp_path / "used").mkdir()
    (tmp_path / "used" / "old.tar").write_bytes(b"")
    with pytest.raises(SystemExit, match="not empty"):
        hub.pack(library, tmp_path / "used")
    other = build_library(tmp_path / "other", ("fg_a",), ("bg_a",))
    with pytest.raises(SystemExit, match="da2-small"):
        hub.pack(other, tmp_path / "packed-other")
