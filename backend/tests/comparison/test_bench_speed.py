"""The speed benchmark: resampling, the summary, and our renderer timed on a written sequence."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "comparison"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import torch  # noqa: E402
from bench_speed import build, main, read_frames, resample  # noqa: E402
from fixture_library import build_library  # noqa: E402

from video_bokeh.scenes.generate import generate_dataset  # noqa: E402

SIZE = 128
FRAMES = 3


@pytest.fixture(scope="module")
def data_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One sequence of three frames with its layers and our bokeh, written on the CPU."""
    tmp = tmp_path_factory.mktemp("speed")
    library = build_library(tmp / "library", ("fg_a", "fg_b"), ("bg_a", "bg_b"))
    root = tmp / "data"
    written = generate_dataset(
        library, root, 1, FRAMES, SIZE, 0, n_objects_max=2, layers=True, bokeh=True
    )
    assert written == 1
    return root


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_resample_takes_every_other_pixel_down_and_repeats_each_up() -> None:
    a = np.arange(16, dtype=np.float32).reshape(4, 4)
    assert np.array_equal(resample(a, 2), a[::2, ::2])
    assert np.array_equal(resample(a, 8), a.repeat(2, axis=0).repeat(2, axis=1))
    assert resample(a, 4) is a


def test_resample_keeps_the_order_of_the_strides() -> None:
    # Colors stored pixel by pixel, seen channel first, as the sequence reader gives them.
    chw = (
        np.random.default_rng(0).random((4, 4, 3), dtype=np.float32).transpose(2, 0, 1)
    )
    for size in (2, 8):
        out = resample(chw, size)
        assert np.array_equal(np.argsort(out.strides), np.argsort(chw.strides))
        assert np.array_equal(out, resample(np.ascontiguousarray(chw), size))


def test_resample_refuses_a_frame_that_is_not_square() -> None:
    with pytest.raises(ValueError, match="square"):
        resample(np.zeros((4, 6), dtype=np.float32), 8)


def test_the_inputs_are_laid_out_alike_at_every_size(data_root: Path) -> None:
    seq = data_root / "sequences" / "0001"
    for name in ("ours", "ours_one_frame"):
        method = build(name, torch.device("cpu"))
        layouts = set()
        for size in (64, SIZE, 256):
            inputs = method.prepare(next(read_frames(seq, size)))
            layouts.add(
                tuple(
                    tuple(np.argsort(v.stride()))
                    for v in inputs.values()
                    if torch.is_tensor(v) and v.dim() > 2 and v.numel()
                )
            )
        assert len(layouts) == 1, name


def test_ours_times_every_frame_after_a_whole_pass(
    data_root: Path, tmp_path: Path
) -> None:
    out = tmp_path / "speed.jsonl"
    args = ["--device", "cpu", "--threads", "2", "--data-root", str(data_root)]
    main(["run", "--method", "ours", *args, "--output", str(out)])
    main(
        [
            "run",
            "--method",
            "ours_one_frame",
            *args,
            "--size",
            "256",
            "--output",
            str(out),
        ]
    )
    layers, one_frame = _records(out)
    assert (layers["warmup"], len(layers["ms"]), layers["frames"]) == (3, 3, 3)
    assert (layers["size"], layers["render_size"], layers["threads"]) == (
        SIZE,
        f"{SIZE}x{SIZE}",
        2,
    )
    # Stage B wrote bokeh/ with the same renderer, three frames at a time.
    assert layers["check"]["stream"] == "bokeh"
    assert layers["check"]["max_levels"] <= 1
    assert layers["card"] is None and layers["peak_mib"] is None
    assert (one_frame["size"], one_frame["render_size"]) == (256, "256x256")
    assert one_frame["check"] is None


def test_the_summary_pools_every_timed_frame(tmp_path: Path) -> None:
    def record(sequence: str, objects: int, ms: list[float]) -> dict:
        return {
            "method": "ours",
            "device": "cuda",
            "size": 1024,
            "render_size": "1024x1024",
            "sequence": sequence,
            "seed": 7,
            "objects": objects,
            "frames": len(ms),
            "warmup": len(ms),
            "ms": ms,
            "peak_mib": 10.0 * objects,
            "check": None,
        }

    lines = [record("b", 2, [3.0, 4.0]), record("a", 1, [1.0, 2.0])]
    path = tmp_path / "speed.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in lines))
    main(["summary", str(path), "--out-dir", str(tmp_path)])
    with (tmp_path / "method-speed.csv").open(newline="") as f:
        (pooled,) = csv.DictReader(f)
    assert (pooled["sequences"], pooled["frames_timed"]) == ("2", "4")
    assert (pooled["mean_ms"], pooled["median_ms"]) == ("2.5", "2.5")
    assert (pooled["q1_ms"], pooled["q3_ms"], pooled["peak_gpu_mib"]) == (
        "1.75",
        "3.25",
        "20.0",
    )
    with (tmp_path / "method-speed-sequences.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert [(r["sequence"], r["objects"], r["median_ms"]) for r in rows] == [
        ("a", "1", "1.5"),
        ("b", "2", "3.5"),
    ]
