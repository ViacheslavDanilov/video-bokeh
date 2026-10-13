"""MAGICK acquisition preserves pools and retries temporary HTTP failures."""

from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

import httpx
import pytest
from httpx import Client

from video_bokeh.acquire import magick


@pytest.fixture
def source(tmp_path: Path) -> Path:
    metadata = tmp_path / "source.csv"
    metadata.write_text("page_id,picked\naa,hand\nbb,hand\ncc,hand\ndd,hand\n")
    return metadata


def _cli(monkeypatch, source: Path, pool: Path, count: int) -> int:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "magick",
            "--metadata",
            str(source),
            "--output",
            str(pool),
            "--count",
            str(count),
            "--seed",
            "11",
        ],
    )
    return magick.main()


def _http(monkeypatch, handler) -> None:
    monkeypatch.setattr(
        magick.httpx, "Client", lambda: Client(transport=httpx.MockTransport(handler))
    )


@pytest.mark.parametrize(
    ("status", "retry_after", "delay"),
    [
        (429, "12", 12),
        (503, None, 5),
        (500, "invalid", 5),
        (429, "Thu, 01 Jan 1970 00:02:00 GMT", 20),
    ],
)
def test_temporary_failure_then_success(
    monkeypatch, tmp_path: Path, source: Path, status, retry_after, delay
) -> None:
    requests = []
    sleeps = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            headers = {"Retry-After": retry_after} if retry_after else {}
            return httpx.Response(status, headers=headers)
        return httpx.Response(200, content=b"image")

    _http(monkeypatch, respond)
    monkeypatch.setattr(magick.time, "sleep", sleeps.append)
    monkeypatch.setattr(magick.time, "time", lambda: 100)
    pool = tmp_path / "pool"
    assert _cli(monkeypatch, source, pool, 1) == 0
    assert len(requests) == 2
    assert sleeps == [delay]
    assert list((pool / "images").rglob("*.png"))[0].read_bytes() == b"image"


def test_persistent_429_stops_after_seven_attempts(
    monkeypatch, tmp_path: Path, source: Path, capsys
) -> None:
    requests = []
    sleeps = []

    def respond(request):
        requests.append(request)
        return httpx.Response(429)

    _http(monkeypatch, respond)
    monkeypatch.setattr(magick.time, "sleep", sleeps.append)
    pool = tmp_path / "pool"
    assert _cli(monkeypatch, source, pool, 1) == 2
    assert len(requests) == 7
    assert sleeps == [5, 10, 20, 40, 60, 60]
    assert "FAIL" in capsys.readouterr().err
    assert not list((pool / "images").rglob("*.png"))
    assert (pool / "metadata.csv").read_text() == "page_id,picked\n"


def test_404_is_not_retried(monkeypatch, tmp_path: Path, source: Path) -> None:
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(404)

    _http(monkeypatch, respond)
    assert _cli(monkeypatch, source, tmp_path / "pool", 1) == 2
    assert len(requests) == 1


def test_fresh_pool_uses_sample_order(
    monkeypatch, tmp_path: Path, source: Path
) -> None:
    _http(monkeypatch, lambda request: httpx.Response(200, content=b"image"))
    pool = tmp_path / "pool"
    assert _cli(monkeypatch, source, pool, 4) == 0
    with (pool / "metadata.csv").open() as f:
        assert [r["page_id"] for r in csv.DictReader(f)] == random.Random(11).sample(
            ["aa", "bb", "cc", "dd"], 4
        )
    before = (pool / "metadata.csv").read_bytes()

    def offline(request):
        pytest.fail("Existing images must not be requested")

    _http(monkeypatch, offline)
    assert _cli(monkeypatch, source, pool, 4) == 0
    assert (pool / "metadata.csv").read_bytes() == before


def test_existing_rows_stay_first_and_new_rows_follow_sample_order(
    monkeypatch, tmp_path: Path, source: Path
) -> None:
    pool = tmp_path / "pool"
    pool.mkdir()
    prefix = "page_id,picked\ncc,hand\naa,hand\nzz,auto\n"
    (pool / "metadata.csv").write_text(prefix)
    _http(monkeypatch, lambda request: httpx.Response(200, content=b"image"))
    assert _cli(monkeypatch, source, pool, 4) == 0
    new = [
        name
        for name in random.Random(11).sample(["aa", "bb", "cc", "dd"], 4)
        if name not in {"cc", "aa"}
    ]
    assert (pool / "metadata.csv").read_text() == prefix + "".join(
        f"{name},hand\n" for name in new
    )
