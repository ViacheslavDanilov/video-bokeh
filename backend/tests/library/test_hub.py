"""A library packed into shards for Hugging Face, and fetched back into the layout Stage B reads."""

from __future__ import annotations

import io
import json
import shutil
import sys
import tarfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# The fixture library lives with the API tests, which use it too.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from fixture_library import build_library  # noqa: E402
from huggingface_hub import DatasetCard  # noqa: E402
from huggingface_hub.errors import EntryNotFoundError  # noqa: E402

from video_bokeh.core._library import list_backgrounds, list_foregrounds  # noqa: E402
from video_bokeh.core._split import listed_test_foregrounds  # noqa: E402
from video_bokeh.library import hub  # noqa: E402
from video_bokeh.scenes.generate import generate_dataset  # noqa: E402


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
    for name in ("train-00001.tar", "train-00002.tar"):
        shutil.move(packed / "library" / "foregrounds" / name, held / name)
    downloaded = _hub(monkeypatch, packed)
    fetched = tmp_path / "fetched"

    missing = hub.fetch("someone/some-library", fetched)
    assert missing == [
        "foregrounds/train-00001.tar",
        "foregrounds/train-00002.tar",
    ]
    assert list_foregrounds(fetched) == ["fg_a"]
    assert list_backgrounds(fetched) == ["bg_a", "bg_b"]

    for name in ("train-00001.tar", "train-00002.tar"):
        shutil.move(held / name, packed / "library" / "foregrounds" / name)
    downloaded.clear()
    assert hub.fetch("someone/some-library", fetched) == []
    assert downloaded == [
        "library/index.json",
        "library/foregrounds/train-00001.tar",
        "library/foregrounds/train-00002.tar",
    ]
    assert list_foregrounds(fetched) == ["fg_a", "fg_b", "fg_c"]


def test_a_shard_holds_each_item_under_webdataset_names_with_its_depth_preview(
    library: Path, tmp_path: Path
) -> None:
    hub.pack(library, tmp_path / "packed", preview=False)
    shards = tmp_path / "packed" / "library"
    with tarfile.open(shards / "foregrounds" / "train-00000.tar") as tar:
        names = tar.getnames()
        preview = tar.extractfile("fg_a.depth_preview.jpg")
        assert preview is not None
        with Image.open(preview) as image:
            assert (image.format, image.mode) == ("JPEG", "RGB")
            side = image.width
    assert names[:5] == [
        "fg_a.rgb.png",
        "fg_a.alpha.png",
        "fg_a.depth.png",
        "fg_a.json",
        "fg_a.depth_preview.jpg",
    ]
    with Image.open(library / "foregrounds" / "fg_a" / "rgb.png") as image:
        assert side == image.width  # the preview is drawn at the item's size
    with tarfile.open(shards / "backgrounds" / "train-00000.tar") as tar:
        assert tar.getnames()[:3] == [
            "bg_a.rgb.png",
            "bg_a.depth.png",
            "bg_a.depth_preview.jpg",
        ]


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("../outside.rgb.png", tarfile.REGTYPE),
        ("nested/fg_x.rgb.png", tarfile.REGTYPE),
        ("fg_x.rgb.png", tarfile.SYMTYPE),
    ],
)
def test_fetching_refuses_a_shard_member_that_is_not_a_plain_item_file(
    library: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    kind: bytes,
) -> None:
    packed = tmp_path / "packed"
    hub.pack(library, packed, preview=False)
    shard = packed / "library" / "backgrounds" / "train-00000.tar"
    with tarfile.open(shard, "a") as tar:
        member = tarfile.TarInfo(name)
        member.type, member.linkname = kind, "/etc/passwd"
        tar.addfile(member, io.BytesIO(b""))
    _hub(monkeypatch, packed)
    fetched = tmp_path / "fetched"
    with pytest.raises(SystemExit, match="unexpected member"):
        hub.fetch("someone/some-library", fetched)
    written = {p.relative_to(fetched).as_posix() for p in fetched.rglob("*.png")}
    assert all(w.startswith(("foregrounds/", "backgrounds/bg_")) for w in written)
    assert not (fetched / "outside.rgb.png").exists()
    assert not (fetched / "backgrounds" / "fg_x").exists()


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
            items = {name.split(".")[0] for name in tar.getnames()}
        assert len(items) == 1


def test_the_package_carries_its_card_and_its_counts(
    library: Path, tmp_path: Path
) -> None:
    hub.pack(library, tmp_path / "packed")
    index = json.loads((tmp_path / "packed" / hub.INDEX).read_text())
    assert index["foregrounds"]["items"] == 3
    assert index["backgrounds"]["items"] == 2
    card = (tmp_path / "packed" / "README.md").read_text()
    assert "license: cc-by-nc-4.0" in card
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
    assert meta["configs"] == [
        {
            "config_name": kind,
            "data_files": [
                {"split": split, "path": f"library/{kind}/{split}-*.tar"}
                for split in ("train", "test")
            ],
            **({"default": True} if kind == "foregrounds" else {}),
        }
        for kind in ("foregrounds", "backgrounds")
    ]
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
    assert "train-00001.tar" in card
    assert f"fetch --repo {hub.REPO} " in card
    # No figure was drawn, so the card shows none; the whole library is in it.
    assert "assets/" not in card
    assert "Upload status" not in card
    assert "@misc{danilov2026videobokeh," in card
    assert "Danilov, Viacheslav and Dewil, Valéry and Arias, Pablo" in card


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


def test_the_preview_draws_disparity_only_where_the_matte_reaches_its_core(
    library: Path,
) -> None:
    from video_bokeh.library import _preview

    # A faint halo on the left, as MAGICK's mattes have, and real matte on the right.
    alpha = np.zeros((64, 64), dtype=np.uint8)
    alpha[:, :32] = 5  # 0.02
    alpha[:, 32:] = 13  # 0.05
    Image.fromarray(alpha).save(library / "foregrounds" / "fg_a" / "alpha.png")
    disparity = np.asarray(_preview._foreground(library, "fg_a")[2])
    side = disparity.shape[0]
    assert tuple(disparity[side // 2, side // 4]) == _preview._OUTSIDE
    assert tuple(disparity[side // 2, 3 * side // 4]) != _preview._OUTSIDE


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
        "library/backgrounds/train-00000.tar",
        "library/foregrounds/train-00000.tar",
        "library/foregrounds/train-00002.tar",
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


TEST_FG = min(listed_test_foregrounds())


@pytest.fixture
def split_library(tmp_path: Path) -> Path:
    """Two foregrounds and two backgrounds in train, one of each in test."""
    return build_library(
        tmp_path / "split-library",
        ("fg_a", "fg_b", TEST_FG),
        ("train__h_a", "train__h_b", "testval__h_c"),
        estimator="da2-large",
    )


def test_a_shard_holds_one_split_and_the_card_counts_each(
    split_library: Path, tmp_path: Path
) -> None:
    index = hub.pack(split_library, tmp_path / "packed", preview=False)
    assert [
        (s["file"], s["split"], s["items"]) for s in index["foregrounds"]["shards"]
    ] == [
        ("foregrounds/train-00000.tar", "train", 2),
        ("foregrounds/test-00000.tar", "test", 1),
    ]
    with tarfile.open(tmp_path / "packed/library/backgrounds/test-00000.tar") as tar:
        assert {n.split(".")[0] for n in tar.getnames()} == {"testval__h_c"}
    card = " ".join((tmp_path / "packed" / "README.md").read_text().split())
    assert "| foregrounds | 2 | 1 |" in card
    assert "| backgrounds | 2 | 1 |" in card


@pytest.fixture
def fixed_set(split_library: Path, tmp_path: Path) -> Path:
    """Two sequences of the test split, with every stream the card describes."""
    out = tmp_path / "fixed-set"
    generate_dataset(
        split_library,
        out,
        2,
        3,
        32,
        seed=1000,
        n_objects_max=1,
        bokeh=True,
        flow=True,
        flow_back=True,
        occlusion=True,
        split="test",
    )
    return out


def test_fetching_a_packed_fixed_set_gives_back_what_the_writer_wrote(
    split_library: Path,
    fixed_set: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packed = tmp_path / "packed"
    hub.pack(split_library, packed, preview=False)
    index = hub.pack_sequences(fixed_set, packed)
    assert (index["items"], index["frames"], index["size"]) == (2, 3, 32)
    assert index["bokeh_strength"] == 16.0
    _hub(monkeypatch, packed)
    fetched = tmp_path / "fetched"
    assert hub.fetch_sequences("someone/some-library", fetched) == []

    got = {k: v for k, v in _files(fetched).items() if not k.startswith(".fetched/")}
    assert got == _files(fixed_set)
    assert not list(fetched.glob("tmp*"))


def test_a_sequence_is_one_sample_named_as_webdataset_names_one(
    split_library: Path, fixed_set: Path, tmp_path: Path
) -> None:
    packed = tmp_path / "packed"
    hub.pack(split_library, packed, preview=False)
    hub.pack_sequences(fixed_set, packed)
    with tarfile.open(packed / "sequences" / "test-00000.tar") as tar:
        names = tar.getnames()
        record = json.load(tar.extractfile("0001.json"))
    assert {n.split(".")[0] for n in names} == {"0001", "0002"}
    first = [n.partition(".")[2] for n in names if n.startswith("0001.")]
    second = [n.partition(".")[2] for n in names if n.startswith("0002.")]
    assert first == second  # every sample holds the same members
    assert first[:3] == [
        "all_in_focus.01.png",
        "all_in_focus.02.png",
        "all_in_focus.03.png",
    ]
    assert "flow.03.png" not in first and "flow_back.01.png" not in first
    assert {"bokeh.01.png", "focus.json", "alpha.01.tif", "occlusion.02.png"} <= set(
        first
    )
    assert record["seed"] == "1000"
    assert [o["foreground"] for o in record["objects"]] == [TEST_FG]


def test_the_card_describes_the_fixed_set_when_there_is_one(
    split_library: Path, fixed_set: Path, tmp_path: Path
) -> None:
    packed = tmp_path / "packed"
    hub.pack(split_library, packed, preview=False)
    hub.pack_sequences(fixed_set, packed)
    card = (packed / "README.md").read_text()
    assert _front_matter(card)["configs"][-1] == {
        "config_name": "sequences",
        "data_files": [{"split": "test", "path": "sequences/test-*.tar"}],
    }
    assert "$" not in card
    prose = " ".join(card.split())
    assert "a fixed set of 2 sequences that Stage B wrote from the test split" in prose
    assert "Each sequence has 3 frames at 32 × 32 and 1 object." in prose
    assert "strength `k = 16`" in prose
    assert f"fetch-sequences --repo {hub.REPO}" in prose
    assert "sequences/test-00000.tar" in card


def test_packing_a_fixed_set_refuses_what_the_card_does_not_describe(
    split_library: Path, fixed_set: Path, tmp_path: Path
) -> None:
    packed = tmp_path / "packed"
    with pytest.raises(SystemExit, match="pack the library there first"):
        hub.pack_sequences(fixed_set, packed)
    hub.pack(split_library, packed, preview=False)
    train = tmp_path / "train-run"
    generate_dataset(split_library, train, 1, 3, 32, seed=0, n_objects_max=1)
    with pytest.raises(SystemExit, match="drew its assets from train"):
        hub.pack_sequences(train, packed)
    partial = tmp_path / "partial"
    generate_dataset(
        split_library, partial, 1, 3, 32, seed=0, n_objects_max=1, split="test"
    )
    with pytest.raises(SystemExit, match="has no bokeh, flow, flow_back, occlusion"):
        hub.pack_sequences(partial, packed)


def test_fetching_a_fixed_set_writes_its_records_only_once_it_is_whole(
    split_library: Path,
    fixed_set: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packed = tmp_path / "packed"
    hub.pack(split_library, packed, preview=False)
    hub.pack_sequences(fixed_set, packed, shard_bytes=1)  # one sequence per shard
    held = tmp_path / "held" / "test-00001.tar"
    held.parent.mkdir()
    shutil.move(packed / "sequences" / "test-00001.tar", held)
    _hub(monkeypatch, packed)
    fetched = tmp_path / "fetched"
    assert hub.fetch_sequences("someone/some-library", fetched) == ["test-00001.tar"]
    assert (fetched / "sequences" / "0001").is_dir()
    assert not (fetched / "manifest.csv").exists()

    shutil.move(held, packed / "sequences" / "test-00001.tar")
    assert hub.fetch_sequences("someone/some-library", fetched) == []
    assert (fetched / "manifest.csv").read_bytes() == (
        fixed_set / "manifest.csv"
    ).read_bytes()


@pytest.mark.parametrize(
    "name",
    ["../0001.all_in_focus.01.png", "0001.all_in_focus.01.exe", "0001.layers.01.png"],
)
def test_fetching_a_fixed_set_refuses_a_member_it_did_not_pack(
    split_library: Path,
    fixed_set: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    packed = tmp_path / "packed"
    hub.pack(split_library, packed, preview=False)
    hub.pack_sequences(fixed_set, packed)
    with tarfile.open(packed / "sequences" / "test-00000.tar", "a") as tar:
        tar.addfile(tarfile.TarInfo(name), io.BytesIO(b""))
    _hub(monkeypatch, packed)
    with pytest.raises(SystemExit, match="unexpected member"):
        hub.fetch_sequences("someone/some-library", tmp_path / "fetched")
    assert not (tmp_path / "0001.all_in_focus.01.png").exists()


def test_packing_a_fixed_set_checks_every_sequence_before_it_writes(
    split_library: Path, fixed_set: Path, tmp_path: Path
) -> None:
    packed = tmp_path / "packed"
    hub.pack(split_library, packed, preview=False)
    (fixed_set / "sequences" / "0002" / "occlusion" / "01.png").unlink()
    with pytest.raises(SystemExit, match="sequence 0002 holds other files than 0001"):
        hub.pack_sequences(fixed_set, packed)
    shutil.rmtree(fixed_set / "sequences" / "0002")
    with pytest.raises(SystemExit, match="lists sequence 0002, which is not there"):
        hub.pack_sequences(fixed_set, packed)
    assert not (packed / "sequences").exists()  # refused before a shard was opened


def test_fetching_a_fixed_set_refuses_a_link_member(
    split_library: Path,
    fixed_set: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packed = tmp_path / "packed"
    hub.pack(split_library, packed, preview=False)
    hub.pack_sequences(fixed_set, packed)
    with tarfile.open(packed / "sequences" / "test-00000.tar", "a") as tar:
        member = tarfile.TarInfo("0003.all_in_focus.01.png")
        member.type, member.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tar.addfile(member)
    _hub(monkeypatch, packed)
    with pytest.raises(SystemExit, match="unexpected member"):
        hub.fetch_sequences("someone/some-library", tmp_path / "fetched")
    assert not (tmp_path / "fetched" / "sequences" / "0003").exists()


def test_a_fetched_shard_is_marked_by_its_path_in_the_repository(
    split_library: Path,
    fixed_set: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Both kinds have a train-00000.tar, so a mark by file name alone would skip one.
    packed = tmp_path / "packed"
    hub.pack(split_library, packed, preview=False)
    hub.pack_sequences(fixed_set, packed)
    _hub(monkeypatch, packed)
    library, run = tmp_path / "library", tmp_path / "run"
    hub.fetch("someone/some-library", library)
    hub.fetch_sequences("someone/some-library", run)
    assert sorted(p.name for p in (library / ".fetched").iterdir()) == [
        "library-backgrounds-test-00000.tar.done",
        "library-backgrounds-train-00000.tar.done",
        "library-foregrounds-test-00000.tar.done",
        "library-foregrounds-train-00000.tar.done",
    ]
    assert [p.name for p in (run / ".fetched").iterdir()] == [
        "sequences-test-00000.tar.done"
    ]
    assert list_backgrounds(library) == ["testval__h_c", "train__h_a", "train__h_b"]
