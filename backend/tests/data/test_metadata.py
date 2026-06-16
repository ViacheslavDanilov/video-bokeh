from __future__ import annotations

from data._metadata import read_asset_metadata, write_asset_metadata


def test_metadata_roundtrips(tmp_path) -> None:
    meta = {
        "estimator": "da2-large",
        "source_ref": "0L/abc.png",
        "neutral_bg_seed": 0,
        "nb_pixels_remove": 5,
        "alpha_threshold": 0.04,
        "low_pct": 2.0,
        "raw_p01": 0.12,
        "raw_p99": 0.94,
        "core_frac": 0.31,
        "n_low_outliers": 4,
        "low_confidence": False,
    }
    write_asset_metadata(tmp_path, meta)
    assert (tmp_path / "meta.json").exists()
    assert read_asset_metadata(tmp_path) == meta


def test_read_missing_metadata_returns_none(tmp_path) -> None:
    assert read_asset_metadata(tmp_path) is None
