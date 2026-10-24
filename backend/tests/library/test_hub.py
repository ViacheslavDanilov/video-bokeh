"""A library packed into shards for Hugging Face, and fetched back into the layout Stage B reads."""

from __future__ import annotations

import json
import shutil
import sys
import tarfile
from pathlib import Path

import pytest
from PIL import Image

# The fixture library lives with the API tests, which use it too.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from fixture_library import build_library  # noqa: E402
from huggingface_hub import DatasetCard  # noqa: E402
from huggingface_hub.errors import EntryNotFoundError  # noqa: E402

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
        source = packed / kwargs["filename"]
        if not source.exists():
            raise EntryNotFoundError(kwargs["filename"])
        target = Path(kwargs["local_dir"]) / kwargs["filename"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
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
    fetched = tmp_path / "fetched"
    assert hub.fetch("someone/some-library", fetched) == []

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


def test_a_repository_uploaded_in_parts_is_fetched_in_parts(
    library: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packed = tmp_path / "packed"
    hub.pack(library, packed, shard_bytes=1)
    held = tmp_path / "not-uploaded-yet"
    held.mkdir()
    for name in ("foregrounds-00001.tar", "foregrounds-00002.tar"):
        shutil.move(packed / "library" / "foregrounds" / name, held / name)
    downloaded = _hub(monkeypatch, packed)
    fetched = tmp_path / "fetched"

    missing = hub.fetch("someone/some-library", fetched)
    assert missing == [
        "foregrounds/foregrounds-00001.tar",
        "foregrounds/foregrounds-00002.tar",
    ]
    assert list_foregrounds(fetched) == ["fg_a"]
    assert list_backgrounds(fetched) == ["bg_a", "bg_b"]

    for name in ("foregrounds-00001.tar", "foregrounds-00002.tar"):
        shutil.move(held / name, packed / "library" / "foregrounds" / name)
    downloaded.clear()
    assert hub.fetch("someone/some-library", fetched) == []
    assert downloaded == [
        "library/index.json",
        "library/foregrounds/foregrounds-00001.tar",
        "library/foregrounds/foregrounds-00002.tar",
    ]
    assert list_foregrounds(fetched) == ["fg_a", "fg_b", "fg_c"]


def test_a_shard_closes_near_its_size_and_never_splits_an_item(
    library: Path,
    tmp_path: Path,
) -> None:
    index = hub.pack(library, tmp_path / "packed", shard_bytes=1)
    assert [s["items"] for s in index["foregrounds"]["shards"]] == [1, 1, 1]
    shards = sorted((tmp_path / "packed" / "library" / "foregrounds").glob("*.tar"))
    assert len(shards) == 3  # every item overflows a 1-byte shard, so one item each
    for shard in shards:
        with tarfile.open(shard) as tar:
            items = {Path(name).parts[1] for name in tar.getnames()}
        assert len(items) == 1


def test_the_package_carries_its_card_and_its_counts(
    library: Path, tmp_path: Path
) -> None:
    hub.pack(library, tmp_path / "packed")
    index = json.loads((tmp_path / "packed" / hub.INDEX).read_text())
    assert index["foregrounds"]["items"] == 3
    assert index["backgrounds"]["items"] == 2
    card = (tmp_path / "packed" / "README.md").read_text()
    assert "license: cc-by-nc-4.0" in card and "viewer: false" in card
    prose = " ".join(card.split())  # the template wraps its lines
    assert "3 foregrounds" in prose and "2 background photos" in prose


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


def _front_matter(card: str) -> dict:
    return DatasetCard(card).data.to_dict()


def test_the_card_follows_the_hub_metadata_and_counts_what_it_holds(
    library: Path, tmp_path: Path
) -> None:
    hub.pack(library, tmp_path / "packed", shard_bytes=1, preview=False)
    card = (tmp_path / "packed" / "README.md").read_text()
    meta = _front_matter(card)
    assert meta["license"] == "cc-by-nc-4.0"
    assert meta["viewer"] is False
    assert "image" in meta["tags"]
    assert set(meta["task_categories"]) == {"image-to-image", "depth-estimation"}
    assert meta["size_categories"] == ["10K<n<100K"]
    assert meta["source_datasets"] == ["OneOverZero/MAGICK", "BG-20k"]
    assert meta["pretty_name"] == "Video Bokeh"
    # Every number is filled in from the index, and no placeholder is left.
    assert "$" not in card
    assert "| items | 3 | 2 |" in card
    assert "| image size | 64 × 64 | 192 × 192 |" in card
    assert "| tar shards | 3 | 2 |" in card
    assert "backgrounds-00001.tar" in card
    assert f"fetch --repo {hub.REPO} " in card
    # No figure was drawn, so the card shows none; the whole library is in it.
    assert "assets/" not in card
    assert "Upload status" not in card
    assert "@misc{danilov2026videobokeh," in card
    assert "Danilov, Viacheslav and Dewil, Val{\\'e}ry and Arias, Pablo" in card
    for key in ("burgert2024magick", "li2022bridging", "yang2024depthanythingv2"):
        assert f"{{{key}," in card


@pytest.fixture(autouse=True)
def short_video(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sequences of 4 small frames, so every test that draws the preview stays quick."""
    monkeypatch.setattr("video_bokeh.library._preview.VIDEO_FRAMES", 4)
    monkeypatch.setattr("video_bokeh.library._preview.VIDEO_PANEL", 128)


def _video_frames(path: Path) -> int:
    import imageio.v2 as iio

    with iio.get_reader(path) as reader:
        return sum(1 for _ in reader)


def test_the_preview_is_a_figure_and_a_video_the_card_shows(
    library: Path, tmp_path: Path
) -> None:
    hub.pack(library, tmp_path / "packed")
    preview = tmp_path / "packed" / hub.PREVIEW
    with Image.open(preview) as image:
        assert image.format == "JPEG"
        width, height = image.size
    assert 2400 <= width <= 2600
    assert height < width
    assert preview.stat().st_size <= 3 * 10**6
    # Three sequences of 4 frames each.
    assert _video_frames(tmp_path / "packed" / hub.VIDEO) == 12
    card = (tmp_path / "packed" / "README.md").read_text()
    assert f"]({hub.PREVIEW})" in card
    assert f"datasets/{hub.REPO}/resolve/main/{hub.VIDEO}" in card


def test_the_preview_is_drawn_again_of_the_items_and_sequences_given(
    library: Path, tmp_path: Path
) -> None:
    packed = tmp_path / "packed"
    hub.pack(library, packed)
    with Image.open(packed / hub.PREVIEW) as image:
        two_rows = image.height  # of the fixture's three foregrounds
    hub.main(
        [
            "preview",
            "--library-root",
            str(library),
            "--packed",
            str(packed),
            "--repo",
            "someone/library",
            "--foregrounds",
            "fg_b",
            "--backgrounds",
            "bg_a",
            "--seeds",
            "7",
        ]
    )
    with Image.open(packed / hub.PREVIEW) as image:
        # One foreground fills one row of the two the fixture's three take.
        assert image.height < two_rows
    assert _video_frames(packed / hub.VIDEO) == 4
    card = (packed / "README.md").read_text()
    assert "datasets/someone/library/resolve/main/" in card
    assert "fetch --repo someone/library " in card


def test_the_figure_refuses_more_items_than_it_holds(
    library: Path, tmp_path: Path
) -> None:
    packed = tmp_path / "packed"
    hub.pack(library, packed, preview=False)
    with pytest.raises(SystemExit, match="3 backgrounds at most"):
        hub.preview(library, packed, backgrounds=["bg_a", "bg_b", "bg_a", "bg_b"])


def test_staging_refuses_a_folder_packed_before_the_video_until_it_has_one(
    library: Path, tmp_path: Path
) -> None:
    packed, staged = tmp_path / "packed", tmp_path / "staged"
    hub.pack(library, packed)
    (packed / hub.VIDEO).unlink()
    with pytest.raises(SystemExit, match="run preview on it first"):
        hub.stage(packed, staged, every=1)
    hub.preview(library, packed)
    assert hub.stage(packed, staged, every=1) == (2, 2)
    assert (staged / hub.VIDEO).samefile(packed / hub.VIDEO)


def test_staging_takes_every_nth_shard_and_the_card_says_how_much_is_online(
    library: Path, tmp_path: Path
) -> None:
    packed, staged = tmp_path / "packed", tmp_path / "staged"
    hub.pack(library, packed, shard_bytes=1)  # one item per shard: 3 and 2
    assert hub.stage(packed, staged, every=2) == (3, 5)

    tars = sorted(p.relative_to(staged).as_posix() for p in staged.rglob("*.tar"))
    assert tars == [
        "library/backgrounds/backgrounds-00000.tar",
        "library/foregrounds/foregrounds-00000.tar",
        "library/foregrounds/foregrounds-00002.tar",
    ]
    for name in [*tars, hub.PREVIEW, hub.VIDEO]:
        assert (staged / name).samefile(packed / name)  # linked, not copied
    assert (staged / hub.INDEX).read_bytes() == (packed / hub.INDEX).read_bytes()
    card = (staged / "README.md").read_text()
    assert "## Upload status" in card
    assert "3 of 5 shards are online" in card
    assert "2 of the 3 foregrounds and 1 of the 2 backgrounds" in card
    assert f"]({hub.PREVIEW})" in card


def test_staging_every_shard_gives_the_card_of_the_whole_library(
    library: Path, tmp_path: Path
) -> None:
    packed, staged = tmp_path / "packed", tmp_path / "staged"
    hub.pack(library, packed, shard_bytes=1, preview=False)
    assert hub.stage(packed, staged, every=1) == (5, 5)
    assert (staged / "README.md").read_text() == (packed / "README.md").read_text()
    assert not (staged / "assets").exists()


def test_staging_refuses_a_used_folder_and_a_step_below_one(
    library: Path, tmp_path: Path
) -> None:
    hub.pack(library, tmp_path / "packed", preview=False)
    with pytest.raises(SystemExit, match="--every"):
        hub.stage(tmp_path / "packed", tmp_path / "staged", every=0)
    (tmp_path / "used").mkdir()
    (tmp_path / "used" / "old.tar").write_bytes(b"")
    with pytest.raises(SystemExit, match="not empty"):
        hub.stage(tmp_path / "packed", tmp_path / "used", every=2)
