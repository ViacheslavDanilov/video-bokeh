"""`acquire.classify --keep-existing` classifies only what a grown pool lacks."""

from __future__ import annotations

import csv
from pathlib import Path

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
