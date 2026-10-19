"""The comparison's summary: means over sequences and the table, on records with known sums."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "comparison"))

from summary import (  # noqa: E402
    check_same_sequences,
    collect,
    summarize,
    table,
)


def _record(method: str, per_sequence: list[dict]) -> dict:
    return {
        "method": method,
        "reference": "bokeh",
        "band": 16,
        "sequences": [
            {"sequence": f"{i:04d}", "frames": [{}, {}], "mean": mean}
            for i, mean in enumerate(per_sequence, start=1)
        ],
    }


def _mean(psnr, band_psnr, mae, band_mae) -> dict:
    return {"psnr": psnr, "band_psnr": band_psnr, "mae": mae, "band_mae": band_mae}


def test_a_method_is_averaged_over_its_sequences() -> None:
    record = _record(
        "drbokeh", [_mean(40.0, 30.0, 1.0, 3.0), _mean(36.0, 28.0, 2.0, 5.0)]
    )
    row = summarize(record)
    assert (row["psnr"], row["band_psnr"]) == (pytest.approx(38.0), pytest.approx(29.0))
    assert (row["mae"], row["band_mae"]) == (pytest.approx(1.5), pytest.approx(4.0))
    assert row["sequences"] == 2 and row["frames"] == 4


def test_a_sequence_without_a_value_is_left_out_of_that_mean_only() -> None:
    record = _record(
        "drbokeh", [_mean(None, 30.0, 0.0, 0.0), _mean(36.0, 28.0, 2.0, 4.0)]
    )
    row = summarize(record)
    assert row["psnr"] == pytest.approx(
        36.0
    )  # the matching sequence has no finite PSNR
    assert row["band_psnr"] == pytest.approx(29.0)
    assert row["mae"] == pytest.approx(1.0)


def test_a_metric_no_sequence_has_is_none() -> None:
    row = summarize(_record("drbokeh", [_mean(None, None, 0.0, 0.0)]))
    assert row["psnr"] is None and row["band_psnr"] is None


def test_the_table_puts_the_nearest_method_first_and_names_it() -> None:
    far = summarize(_record("any_to_bokeh", [_mean(28.0, 27.0, 6.0, 7.0)]))
    near = summarize(_record("bokehme", [_mean(43.0, 36.0, 0.5, 1.8)]))
    lines = table([far, near]).splitlines()
    assert lines[2].startswith("| BokehMe, hybrid | 1 | 43.0 | 36.0 | 0.50 | 1.80 |")
    assert lines[3].startswith("| Any-to-Bokeh | 1 | 28.0 | 27.0 |")


def test_the_runs_composited_in_gamma_values_are_named_apart() -> None:
    rows = [
        summarize(_record(method, [_mean(40.0, 30.0, 1.0, 3.0)]))
        for method in ("drbokeh_cg", "mpib_rt_cg")
    ]
    text = table(rows)
    assert "| Dr.Bokeh, composited in gamma | 1 |" in text
    assert "| MPIB, composited in gamma | 1 |" in text


def test_a_method_without_a_title_keeps_its_own_name_and_n_a_marks_a_gap() -> None:
    row = summarize(_record("other", [_mean(None, None, 0.0, 0.0)]))
    assert "| other | 1 | n/a | n/a |" in table([row])


def test_only_a_file_under_its_own_methods_name_is_collected(tmp_path: Path) -> None:
    record = _record("drbokeh", [_mean(40.0, 30.0, 1.0, 3.0)])
    (tmp_path / "comparison_drbokeh.json").write_text(json.dumps(record))
    # A copy kept under another name, and the summary this script wrote earlier.
    (tmp_path / "comparison_drbokeh_old.json").write_text(json.dumps(record))
    (tmp_path / "comparison_summary.json").write_text(json.dumps([summarize(record)]))
    assert [row["method"] for row in collect(tmp_path)] == ["drbokeh"]


def test_a_method_with_no_sequence_has_no_values() -> None:
    row = summarize(_record("drbokeh", []))
    assert row["sequences"] == 0 and row["frames"] == 0 and row["psnr"] is None


def test_rows_over_the_same_sequences_pass() -> None:
    a = summarize(_record("drbokeh", [_mean(40.0, 30.0, 1.0, 3.0)]))
    b = summarize(_record("bokehme", [_mean(43.0, 36.0, 0.5, 1.8)]))
    check_same_sequences([a, b])


def test_rows_over_different_sequences_are_refused_naming_the_methods() -> None:
    a = summarize(_record("drbokeh", [_mean(40.0, 30.0, 1.0, 3.0)] * 2))
    b = summarize(_record("bokehme", [_mean(43.0, 36.0, 0.5, 1.8)]))
    with pytest.raises(SystemExit) as refused:
        check_same_sequences([a, b])
    message = str(refused.value)
    assert "drbokeh: 2 sequences" in message and "bokehme: 1 sequences" in message
