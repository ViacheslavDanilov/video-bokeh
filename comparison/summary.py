#!/usr/bin/env python3
"""Collect every ``comparison_<method>.json`` under a data root into one table.

``score.py`` writes one file per method. This reads them all and averages each method over
the sequences, giving the PSNR and the mean absolute difference against our bokeh over the
whole frame and over the edge band. It prints a Markdown table, sorted from the nearest to
ours, and writes ``comparison_summary.json`` beside the sources.

Usage:
    comparison/envs/render/bin/python comparison/summary.py --data-root data/cmp
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

#: The means ``score.py`` records per sequence, in the order the table shows them.
METRICS = ("psnr", "band_psnr", "mae", "band_mae")
#: How each method is named in the table.
TITLES = {
    "bokehme": "BokehMe, hybrid",
    "bokehme_classical": "BokehMe, scatter alone",
    "mpib_rt": "MPIB",
    "mpib_rt_cg": "MPIB, composited in gamma",
    "drbokeh": "Dr.Bokeh",
    "drbokeh_cg": "Dr.Bokeh, composited in gamma",
    "any_to_bokeh": "Any-to-Bokeh",
}


def summarize(record: dict) -> dict:
    """One method's means over its sequences, from the content of its ``score.py`` file.

    A sequence that matches the reference exactly has no finite PSNR and is left out of that
    mean, as ``score.py`` leaves out such frames. A metric no sequence has is ``None``.
    """
    sequences = record["sequences"]
    means = {}
    for key in METRICS:
        values = [s["mean"][key] for s in sequences if s["mean"].get(key) is not None]
        means[key] = float(np.mean(values)) if values else None
    return {
        "method": record["method"],
        "reference": record["reference"],
        "band": record["band"],
        "sequences": len(sequences),
        "sequence_ids": [s["sequence"] for s in sequences],
        "frames": sum(len(s["frames"]) for s in sequences),
        **means,
    }


def table(rows: list[dict]) -> str:
    """The rows as a Markdown table, the nearest to the reference first."""

    def fmt(value: float | None, digits: int = 2) -> str:
        return "n/a" if value is None else f"{value:.{digits}f}"

    ordered = sorted(
        rows, key=lambda r: -(r["psnr"] if r["psnr"] is not None else -1.0)
    )
    lines = [
        "| method | sequences | PSNR (dB) | edge-band PSNR (dB) | MAE | edge-band MAE |",
        "|---|---|---|---|---|---|",
    ]
    for row in ordered:
        title = TITLES.get(row["method"], row["method"])
        lines.append(
            f"| {title} | {row['sequences']} | {fmt(row['psnr'], 1)} | "
            f"{fmt(row['band_psnr'], 1)} | {fmt(row['mae'])} | {fmt(row['band_mae'])} |"
        )
    return "\n".join(lines)


def collect(data_root: Path) -> list[dict]:
    """The summary row of each ``comparison_<method>.json`` that ``score.py`` wrote.

    A file counts only under the name its own record gives, so a copy kept under another
    name, or this script's own output, is not counted twice.
    """
    rows = []
    for path in sorted(data_root.glob("comparison_*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if (
            isinstance(record, dict)
            and path.name == f"comparison_{record.get('method')}.json"
        ):
            rows.append(summarize(record))
    return rows


def check_same_sequences(rows: list[dict]) -> None:
    """Refuse rows made over different sequences: a table compares methods on one set."""
    sets = {row["method"]: tuple(row["sequence_ids"]) for row in rows}
    if len(set(sets.values())) > 1:
        lines = [
            f"  {method}: {len(ids)} sequences, {ids[0]} to {ids[-1]}"
            for method, ids in sets.items()
            if ids
        ]
        raise SystemExit(
            "the score files were made over different sequences, so their means are not "
            "comparable; score them again over the same ones, or use a fresh data root:\n"
            + "\n".join(lines)
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = collect(args.data_root)
    if not rows:
        raise SystemExit(
            f"no comparison_<method>.json under {args.data_root}: run score.py"
        )
    check_same_sequences(rows)
    (args.data_root / "comparison_summary.json").write_text(
        json.dumps(rows, indent=1) + "\n", encoding="utf-8"
    )
    print(table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
