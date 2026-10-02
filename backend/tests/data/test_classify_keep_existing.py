"""`acquire.classify --keep-existing` classifies only what a grown pool lacks."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest
from PIL import Image

from video_bokeh.acquire import classify
from video_bokeh.acquire.classify import read_predictions, unclassified


def test_only_images_without_a_prediction_are_left_to_classify() -> None:
    rows = [{"page_id": p} for p in ("a", "b", "c", "d")]
    kept = [{"page_id": "b", "top_subject": "object"}, {"page_id": "d"}]
    assert unclassified(rows, kept) == [{"page_id": "a"}, {"page_id": "c"}]


def test_kept_predictions_are_read_as_written(tmp_path: Path) -> None:
    path = tmp_path / "predictions.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["page_id", "top_style"])
        writer.writeheader()
        writer.writerow({"page_id": "a", "top_style": "photo"})
    assert read_predictions(path) == [{"page_id": "a", "top_style": "photo"}]


def test_predictions_with_other_columns_are_refused_before_clip_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refused up front: the rewrite after a CLIP run would otherwise fail with the kept
    predictions already truncated away.
    """
    (tmp_path / "images" / "ab").mkdir(parents=True)
    Image.new("RGB", (8, 8)).save(tmp_path / "images" / "ab" / "abc.png")
    (tmp_path / "metadata.csv").write_text("page_id\nabc\n")
    stale = "page_id,top_subject,score_subject_gone\nold,object,0.9\n"
    (tmp_path / "predictions.csv").write_text(stale)

    def _no_clip(*args, **kwargs):
        raise AssertionError("CLIP must not load")

    monkeypatch.setattr(classify.open_clip, "create_model_and_transforms", _no_clip)
    monkeypatch.setattr(
        sys,
        "argv",
        ["classify", "--data-root", str(tmp_path), "--keep-existing"],
    )
    assert classify.main() == 1
    assert (tmp_path / "predictions.csv").read_text() == stale
