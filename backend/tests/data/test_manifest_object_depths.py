from __future__ import annotations

import csv
from pathlib import Path

from data.generate_sequences import (
    MANIFEST_FIELDS,
    SequenceSpec,
    read_manifest,
    write_manifest,
)


def test_object_depths_in_manifest_fields() -> None:
    assert "object_depths" in MANIFEST_FIELDS


def test_manifest_roundtrip_preserves_object_depths(tmp_path: Path) -> None:
    spec = SequenceSpec(
        seq_id=1,
        seed=42,
        n_frames=2,
        size=128,
        bg_ref="bg.jpg",
        object_refs=["a.png", "b.png"],
        channel_refs=["b.png", "a.png"],
        bg_easing="easeInOutSine",
        object_easings=["easeInSine", "easeOutSine"],
        object_depths=[0.8, 0.2],
    )
    path = tmp_path / "manifest.csv"
    write_manifest(path, [spec])

    [loaded] = read_manifest(path)
    assert loaded.object_depths == [0.8, 0.2]


def test_legacy_manifest_without_object_depths_defaults_to_empty(
    tmp_path: Path,
) -> None:
    path = tmp_path / "manifest.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "seq_id",
                "seed",
                "n_frames",
                "size",
                "bg_ref",
                "object_refs",
                "channel_refs",
                "bg_easing",
                "object_easings",
            ],
        )
        writer.writerow(
            [
                "1",
                "42",
                "2",
                "128",
                "bg.jpg",
                "a.png|b.png",
                "b.png|a.png",
                "easeInOutSine",
                "easeInSine|easeOutSine",
            ],
        )

    [loaded] = read_manifest(path)
    assert loaded.object_depths == []
