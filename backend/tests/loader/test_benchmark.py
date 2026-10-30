"""The benchmark drains prefetch before measuring throughput and tensor payloads."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
import torch
from torch.utils.data import DataLoader

from video_bokeh.loader import benchmark as mod
from video_bokeh.loader._stream import DEFAULT_STREAMS


@pytest.mark.parametrize(
    ("workers", "minimum", "warmup", "timed"),
    [
        (0, 1, 1, 1),
        (0, 15, 1, 15),
        (1, 15, 2, 15),
        (4, 20, 8, 20),
        (8, 15, 16, 16),
        (12, 15, 24, 24),
    ],
)
def test_protocol_counts_and_throughput(
    workers: int, minimum: int, warmup: int, timed: int
) -> None:
    draws = []
    readings = []
    ticks = iter([10.0, 12.5])

    def batches():
        for index in range(warmup + timed + 1):
            draws.append(index)
            yield {"n_objects": torch.ones(3, dtype=torch.int64)}

    def clock():
        readings.append(len(draws))
        return next(ticks)

    result = mod.run_protocol(
        batches(), clock, workers=workers, min_timed_batches=minimum
    )

    assert readings == [warmup, warmup + timed]
    assert len(draws) == warmup + timed
    assert result["warmup_batches"] == warmup
    assert result["timed_batches"] == timed
    assert result["timed_items"] == 3 * timed
    assert result["timed_seconds"] == 2.5
    assert result["items_per_second"] == 3 * timed / 2.5


def test_mib_per_item_averages_only_timed_tensor_bytes() -> None:
    warmup = {"n_objects": torch.ones(2), "rgb": torch.empty(2, 1000)}
    batches = [warmup]
    for dtype in (torch.float32, torch.float64):
        batches.append(
            {
                "n_objects": torch.ones(2, dtype=torch.int64),
                "seed": torch.zeros(2, dtype=torch.int64),
                "rgb": torch.empty(2, 3, dtype=dtype),
                "alpha": torch.empty(2, 4, dtype=torch.uint8),
            }
        )
    ticks = iter([0.0, 1.0])
    result = mod.run_protocol(
        batches, lambda: next(ticks), workers=0, min_timed_batches=2
    )

    # 64 and 88 bytes per batch, each of two items, including both metadata tensors.
    assert result["mib_per_item"] == pytest.approx((64 + 88) / 4 / 2**20)


@pytest.mark.parametrize(
    "streams", [None, "layers,object_alphas", "layers,focus", "object_alphas,focus"]
)
def test_gpu_bokeh_requires_all_three_streams(
    streams: str | None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["--library-root", str(tmp_path / "missing"), "--gpu-bokeh"]
    if streams is not None:
        argv.extend(["--streams", streams])
    with pytest.raises(SystemExit) as error:
        mod.main(argv)

    assert error.value.code == 2
    assert (
        "requires the layers, object_alphas and focus streams"
        in capsys.readouterr().err
    )


def test_main_writes_measurements_and_reproduction_metadata(
    library: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "benchmark.json"
    mod.main(
        [
            "--library-root",
            str(library),
            "--workers",
            "0",
            "--frames",
            "2",
            "--size",
            "16",
            "--objects-max",
            "1",
            "--batch-size",
            "2",
            "--min-timed-batches",
            "1",
            "--output",
            str(output),
        ]
    )
    record = json.loads(output.read_text())

    assert {
        key: record[key]
        for key in (
            "library_root",
            "streams",
            "frames",
            "size",
            "objects_min",
            "objects_max",
            "batch_size",
            "workers",
            "seed",
            "gpu_bokeh",
            "device",
            "bokeh_strength",
            "min_timed_batches",
            "unordered",
            "output",
        )
    } == {
        "library_root": str(library),
        "streams": list(DEFAULT_STREAMS),
        "frames": 2,
        "size": 16,
        "objects_min": 1,
        "objects_max": 1,
        "batch_size": 2,
        "workers": 0,
        "seed": 0,
        "gpu_bokeh": False,
        "device": "auto",
        "bokeh_strength": 16.0,
        "min_timed_batches": 1,
        "unordered": False,
        "output": str(output),
    }
    assert record["warmup_batches"] == record["timed_batches"] == 1
    assert record["timed_items"] == 2
    assert record["timed_seconds"] > 0
    assert record["items_per_second"] == 2 / record["timed_seconds"]
    assert record["mib_per_item"] == (2 * 6 * 16**2 * 4 + 16) / 2**20
    assert record["peak_gpu_memory_gib"] is None
    assert record["torch_version"] == torch.__version__
    assert record["resolved_device"] == "cpu"
    assert record["device_name"].startswith("cpu")
    assert record["cpu_count"] is None or record["cpu_count"] > 0
    assert datetime.fromisoformat(record["date"]).utcoffset().total_seconds() == 0
    assert record["git_commit"] is None or len(record["git_commit"]) == 40
    assert capsys.readouterr().out.splitlines() == [
        f"{key}: {record[key]}"
        for key in (
            "warmup_batches",
            "timed_batches",
            "timed_items",
            "timed_seconds",
            "items_per_second",
            "mib_per_item",
        )
    ]


def test_unordered_lets_the_loader_deliver_whichever_batch_is_ready(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    passed: dict[str, object] = {}

    def loader(*args: object, **kwargs: object) -> DataLoader:
        passed.update(kwargs)
        return DataLoader(*args, **kwargs)

    monkeypatch.setattr(mod, "DataLoader", loader)
    output = tmp_path / "benchmark.json"
    argv = ["--library-root", str(library), "--workers", "0", "--frames", "2"]
    argv += ["--size", "16", "--objects-max", "1", "--min-timed-batches", "1"]
    mod.main([*argv, "--unordered", "--output", str(output)])

    assert passed["in_order"] is False
    assert json.loads(output.read_text())["unordered"] is True


def test_an_installed_copy_records_no_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A training project that installs the package keeps it under its own git checkout.
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run(
        [
            *git,
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "t",
        ],
        check=True,
    )
    from video_bokeh.core import _provenance

    installed = tmp_path / ".venv/lib/python3.13/site-packages/video_bokeh/core"
    installed.mkdir(parents=True)
    monkeypatch.setattr(_provenance, "__file__", str(installed / "_provenance.py"))

    assert mod._git_commit() is None


def test_the_source_checkout_records_its_commit() -> None:
    commit = mod._git_commit()

    assert commit is not None
    assert len(commit) == 40
