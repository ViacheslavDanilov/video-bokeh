"""`acquire.bg20k --count` grows a background pool one file at a time, reproducibly."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

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
