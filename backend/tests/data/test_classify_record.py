"""`acquire.classify` records which model made each run's predictions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import torch
from PIL import Image

from video_bokeh.acquire import classify
from video_bokeh.acquire.classify import prediction_fieldnames


class _FakeClip:
    """Stands in for an OpenCLIP model: every image and prompt gets the same features."""

    def eval(self) -> _FakeClip:
        return self

    def encode_text(self, tokens: torch.Tensor) -> torch.Tensor:
        return torch.ones(len(tokens), 4)

    def encode_image(self, images: torch.Tensor) -> torch.Tensor:
        return torch.ones(images.shape[0], 4)


def _fake_open_clip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        classify.open_clip,
        "create_model_and_transforms",
        lambda *args, **kwargs: (_FakeClip(), None, lambda image: torch.zeros(3, 2, 2)),
    )
    monkeypatch.setattr(
        classify.open_clip,
        "get_tokenizer",
        lambda name: lambda prompts: torch.zeros(len(prompts), 1, dtype=torch.long),
    )


def _pool(root: Path, page_ids: list[str]) -> None:
    for page_id in page_ids:
        (root / "images" / page_id[:2]).mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8)).save(root / "images" / page_id[:2] / f"{page_id}.png")
    (root / "metadata.csv").write_text(
        "page_id\n" + "".join(f"{p}\n" for p in page_ids)
    )


def _kept_prediction(root: Path, page_id: str) -> None:
    header = prediction_fieldnames()
    row = [page_id] + ["0"] * (len(header) - 1)
    (root / "predictions.csv").write_text(
        ",".join(header) + "\n" + ",".join(row) + "\n"
    )


def _classify(monkeypatch: pytest.MonkeyPatch, root: Path, *flags: str) -> int:
    monkeypatch.setattr(
        sys,
        "argv",
        ["classify", "--data-root", str(root), "--num-workers", "0", *flags],
    )
    return classify.main()


def test_a_run_records_its_model_beside_its_predictions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_open_clip(monkeypatch)
    _pool(tmp_path, ["aa1", "bb2"])

    assert _classify(monkeypatch, tmp_path, "--model", "M", "--pretrained", "w") == 0

    record = json.loads((tmp_path / "predictions.json").read_text())
    assert record["open_clip_repository"] == classify.OPEN_CLIP_REPOSITORY
    [run] = record["runs"]
    assert (run["rows"], run["model"], run["pretrained"]) == (2, "M", "w")
    assert run["open_clip"] == classify.open_clip.__version__


def test_keeping_predictions_adds_a_run_to_their_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_open_clip(monkeypatch)
    _pool(tmp_path, ["aa1", "bb2"])
    _kept_prediction(tmp_path, "aa1")
    earlier = {"rows": 1, "model": "M", "pretrained": "w", "note": "kept as written"}
    (tmp_path / "predictions.json").write_text(json.dumps({"runs": [earlier]}))

    flags = ("--model", "M", "--pretrained", "w", "--keep-existing")
    assert _classify(monkeypatch, tmp_path, *flags) == 0

    runs = json.loads((tmp_path / "predictions.json").read_text())["runs"]
    assert runs[0] == earlier
    assert (runs[1]["rows"], runs[1]["model"]) == (1, "M")


def test_kept_predictions_without_a_record_are_marked_of_unknown_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_open_clip(monkeypatch)
    _pool(tmp_path, ["aa1", "bb2"])
    _kept_prediction(tmp_path, "aa1")

    assert _classify(monkeypatch, tmp_path, "--keep-existing") == 0

    runs = json.loads((tmp_path / "predictions.json").read_text())["runs"]
    assert [(r["rows"], r["model"]) for r in runs] == [(1, None), (1, "ViT-L-14")]


def test_predictions_another_model_made_are_refused_before_clip_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _no_clip(*args, **kwargs):
        raise AssertionError("CLIP must not load")

    monkeypatch.setattr(classify.open_clip, "create_model_and_transforms", _no_clip)
    _pool(tmp_path, ["aa1", "bb2"])
    _kept_prediction(tmp_path, "aa1")
    record = json.dumps({"runs": [{"rows": 1, "model": "Other", "pretrained": "x"}]})
    (tmp_path / "predictions.json").write_text(record)
    kept = (tmp_path / "predictions.csv").read_text()

    assert _classify(monkeypatch, tmp_path, "--keep-existing") == 1
    assert (tmp_path / "predictions.csv").read_text() == kept
    assert (tmp_path / "predictions.json").read_text() == record
