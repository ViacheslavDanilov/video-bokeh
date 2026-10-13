"""`acquire.bg20k --count` grows a background pool one file at a time, reproducibly."""

from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_bokeh.acquire import bg20k

# The Kaggle upload: two split lists in shard 1, and images spread over numbered shards.
_TRAIN = [f"h_{i:08x}.jpg" for i in range(12)]
_TESTVAL = [f"h_{i:08x}.jpg" for i in range(100, 106)]


@pytest.fixture
def kaggle(tmp_path: Path) -> tuple[Path, list[str]]:
    root = tmp_path / "kaggle"
    lists = root / "1" / "BG-20k"
    lists.mkdir(parents=True)
    (lists / "train.txt").write_text("\n".join(_TRAIN) + "\n")
    (lists / "testval.txt").write_text("\n".join(_TESTVAL) + "\n")
    for i, name in enumerate(_TRAIN):
        shard = root / str(1 + i % 7) / "BG-20k" / "train"
        shard.mkdir(parents=True, exist_ok=True)
        (shard / name).write_bytes(name.encode())
    for i, name in enumerate(_TESTVAL):
        shard = root / str(7 - i % 7) / "BG-20k" / "testval"
        shard.mkdir(parents=True, exist_ok=True)
        (shard / name).write_bytes(name.encode())
    asked: list[str] = []
    return root, asked


class _HTTPError(Exception):
    """What kagglehub raises for a path the upload does not have: requests' HTTPError."""

    def __init__(self, status: int) -> None:
        super().__init__(f"{status} Client Error")
        self.response = type("Response", (), {"status_code": status})()


def _download(kaggle: tuple[Path, list[str]]):
    root, asked = kaggle

    def _fetch(path: str, output_dir: str) -> str:
        asked.append(path)
        source = root / path
        if not source.is_file():
            raise _HTTPError(404)
        dest = Path(output_dir) / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, dest)
        return str(dest)

    return _fetch


def _rows(pool: Path) -> list[tuple[str, str]]:
    with (pool / "metadata.csv").open() as f:
        return [(r["filename"], r["split"]) for r in csv.DictReader(f)]


def test_fills_an_empty_pool_to_the_count(tmp_path: Path, kaggle) -> None:
    pool = tmp_path / "pool"
    bg20k.sample_pool(pool, count=5, seed=11, download=_download(kaggle))
    rows = _rows(pool)
    assert len(rows) == 5
    for name, split in rows:
        assert (pool / "images" / split / name).read_bytes() == name.encode()


def test_the_same_seed_picks_the_same_backgrounds(tmp_path: Path, kaggle) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    bg20k.sample_pool(a, count=6, seed=11, download=_download(kaggle))
    bg20k.sample_pool(b, count=6, seed=11, download=_download(kaggle))
    assert _rows(a) == _rows(b)


def test_growing_a_pool_keeps_what_it_holds(tmp_path: Path, kaggle) -> None:
    """The dev pool's first twenty came from elsewhere; they stay, first, as they are."""
    pool = tmp_path / "pool"
    (pool / "images" / "testval").mkdir(parents=True)
    (pool / "images" / "testval" / "h_00000105.jpg").write_bytes(b"ours")
    (pool / "metadata.csv").write_text("filename,split\nh_00000105.jpg,testval\n")

    bg20k.sample_pool(pool, count=4, seed=11, download=_download(kaggle))

    rows = _rows(pool)
    assert rows[0] == ("h_00000105.jpg", "testval")
    assert len(rows) == 4
    assert len(set(rows)) == 4
    assert (pool / "images" / "testval" / "h_00000105.jpg").read_bytes() == b"ours"


def test_a_pool_already_at_the_count_downloads_nothing(tmp_path: Path, kaggle) -> None:
    pool = tmp_path / "pool"
    bg20k.sample_pool(pool, count=3, seed=11, download=_download(kaggle))
    _, asked = kaggle
    asked.clear()
    bg20k.sample_pool(pool, count=3, seed=11, download=_download(kaggle))
    assert asked == []


def test_a_larger_count_extends_the_same_order(tmp_path: Path, kaggle) -> None:
    """Growing 3 to 6 gives the pool a run straight to 6 would have."""
    grown, direct = tmp_path / "grown", tmp_path / "direct"
    bg20k.sample_pool(grown, count=3, seed=11, download=_download(kaggle))
    bg20k.sample_pool(grown, count=6, seed=11, download=_download(kaggle))
    bg20k.sample_pool(direct, count=6, seed=11, download=_download(kaggle))
    assert _rows(grown) == _rows(direct)


def test_a_failed_download_stops_rather_than_changing_the_sample(
    tmp_path: Path,
    kaggle,
) -> None:
    """Anything but a 404 is not "in another shard", and skipping it would quietly draw
    a different background.
    """
    pool = tmp_path / "pool"
    bg20k.sample_pool(pool, count=2, seed=11, download=_download(kaggle))
    fetch = _download(kaggle)

    def _offline(path: str, output_dir: str) -> str:
        if path.endswith(".txt"):
            return fetch(path, output_dir)
        raise ConnectionError("network is unreachable")

    with pytest.raises(ConnectionError):
        bg20k.sample_pool(pool, count=4, seed=11, download=_offline)
    assert len(_rows(pool)) == 2


def test_the_pool_metadata_has_lf_line_endings(tmp_path: Path, kaggle) -> None:
    pool = tmp_path / "pool"
    bg20k.sample_pool(pool, count=2, seed=11, download=_download(kaggle))
    assert b"\r" not in (pool / "metadata.csv").read_bytes()


@pytest.fixture
def whole_cli(tmp_path: Path, kaggle, monkeypatch):
    root, _ = kaggle
    pool = tmp_path / "pool"
    archive = pool / "datasets" / bg20k.KAGGLE_DATASET / "versions" / "1"
    calls = []
    monkeypatch.setenv("KAGGLEHUB_CACHE", "unused")

    def download(dataset):
        calls.append(dataset)
        assert bg20k.os.environ["KAGGLEHUB_CACHE"] == str(pool.resolve())
        if not archive.exists():
            shutil.copytree(root, archive)
        return str(archive)

    monkeypatch.setitem(
        sys.modules, "kagglehub", SimpleNamespace(dataset_download=download)
    )
    monkeypatch.setattr(sys, "argv", ["bg20k", "--output", str(pool)])
    return pool, archive, calls


@pytest.mark.parametrize("already_downloaded", [False, True])
def test_whole_cli_normalizes_the_archive(
    kaggle, whole_cli, already_downloaded: bool
) -> None:
    pool, archive, calls = whole_cli
    root, _ = kaggle
    if already_downloaded:
        shutil.copytree(root, archive)
    assert bg20k.main() == 0
    assert calls == [bg20k.KAGGLE_DATASET]
    assert set(_rows(pool)) == {
        *((name, "train") for name in _TRAIN),
        *((name, "testval") for name in _TESTVAL),
    }
    assert (pool / "metadata.csv").read_text().splitlines()[0] == "filename,split"
    for name, split in _rows(pool):
        assert (pool / "images" / split / name).read_bytes() == name.encode()
    assert len(list(pool.rglob("*.jpg"))) == len(_TRAIN) + len(_TESTVAL)
    assert not archive.exists()
    assert not list(pool.rglob("*.txt"))


@pytest.mark.parametrize("existing_metadata", [False, True])
def test_whole_cli_keeps_incomplete_archive(
    kaggle, whole_cli, existing_metadata: bool, capsys
) -> None:
    pool, archive, _ = whole_cli
    root, _ = kaggle
    missing = [
        root / "1/BG-20k/train" / _TRAIN[0],
        root / "7/BG-20k/testval" / _TESTVAL[0],
    ]
    for source in missing:
        source.unlink()
    if existing_metadata:
        pool.mkdir()
        bg20k._write_pool(
            pool,
            [(name, "train") for name in _TRAIN]
            + [(name, "testval") for name in _TESTVAL],
        )
    assert bg20k.main() == 2
    assert archive.is_dir()
    assert (archive / "1/BG-20k/train.txt").is_file()
    assert len(list(archive.rglob("*.jpg"))) == len(_TRAIN) + len(_TESTVAL) - 2
    error = capsys.readouterr().err
    assert f"train/{_TRAIN[0]}" in error
    assert f"testval/{_TESTVAL[0]}" in error
    assert "archive kept" in error


def test_whole_cli_repairs_missing_image_on_rerun(whole_cli) -> None:
    pool, archive, calls = whole_cli
    assert bg20k.main() == 0
    before = (pool / "metadata.csv").read_bytes()
    image = pool / "images/train" / _TRAIN[0]
    image.unlink()
    assert bg20k.main() == 0
    assert image.read_bytes() == _TRAIN[0].encode()
    assert (pool / "metadata.csv").read_bytes() == before
    assert len(calls) == 2
    assert not archive.exists()


@pytest.mark.parametrize("identical", [False, True])
@pytest.mark.parametrize("existing_layout", [False, True])
def test_whole_cli_checks_same_split_collisions(
    kaggle, whole_cli, identical: bool, existing_layout: bool, capsys
) -> None:
    pool, archive, _ = whole_cli
    root, _ = kaggle
    if existing_layout:
        assert bg20k.main() == 0
    original = root / "1/BG-20k/train" / _TRAIN[0]
    duplicate = root / "2/BG-20k/train" / _TRAIN[0]
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    duplicate.write_bytes(
        original.read_bytes() if identical else b"x" * original.stat().st_size
    )
    shutil.copystat(original, duplicate)
    assert bg20k.main() == (0 if identical else 2)
    if identical:
        assert not archive.exists()
        assert (pool / "images/train" / _TRAIN[0]).read_bytes() == original.read_bytes()
        assert _rows(pool).count((_TRAIN[0], "train")) == 1
    else:
        assert (archive / original.relative_to(root)).is_file()
        assert (archive / duplicate.relative_to(root)).is_file()
        error = capsys.readouterr().err
        assert str(archive / original.relative_to(root)) in error
        assert str(archive / duplicate.relative_to(root)) in error


def test_whole_cli_keeps_same_names_in_different_splits(kaggle, whole_cli) -> None:
    pool, archive, _ = whole_cli
    root, _ = kaggle
    listing = root / "1/BG-20k/testval.txt"
    listing.write_text(listing.read_text() + _TRAIN[0] + "\n")
    image = root / "1/BG-20k/testval" / _TRAIN[0]
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"different split")
    assert bg20k.main() == 0
    assert (pool / "images/testval" / _TRAIN[0]).read_bytes() == b"different split"
    assert (pool / "images/train" / _TRAIN[0]).read_bytes() == _TRAIN[0].encode()
    assert not archive.exists()


def test_whole_cli_checks_output_files_before_cleanup(whole_cli, monkeypatch) -> None:
    _, archive, _ = whole_cli
    monkeypatch.setattr(bg20k.shutil, "copy", lambda source, dest: None)
    assert bg20k.main() == 2
    assert archive.is_dir()


def test_whole_cli_reports_cleanup_failure(whole_cli, monkeypatch, capsys) -> None:
    pool, archive, _ = whole_cli

    def denied(path):
        assert path == archive
        raise PermissionError("cleanup denied")

    monkeypatch.setattr(bg20k.shutil, "rmtree", denied)
    assert bg20k.main() == 2
    assert archive.is_dir()
    assert all(
        (pool / "images" / split / name).is_file() for name, split in _rows(pool)
    )
    assert "cleanup denied" in capsys.readouterr().err
