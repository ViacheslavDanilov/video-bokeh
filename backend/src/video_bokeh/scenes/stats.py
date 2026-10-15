"""Summarize a written dataset's scene records, focus, and stream sizes."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import median

_STREAMS = (
    "all_in_focus",
    "alpha",
    "disparity",
    "layers",
    "flow",
    "flow_back",
    "bokeh",
)


def _reuse(ids: list[str]) -> dict[str, int]:
    counts = Counter(ids)
    return {"distinct": len(counts), "max_uses": max(counts.values(), default=0)}


def dataset_stats(data_root: Path) -> dict[str, object]:
    """Read the current manifest's sequences without resampling their scenes."""
    for name in ("manifest.csv", "objects.csv", "run.json"):
        if not (data_root / name).is_file():
            raise ValueError(f"missing required dataset record: {data_root / name}")
    with (data_root / "manifest.csv").open(encoding="utf-8", newline="") as f:
        sequences = list(csv.DictReader(f))
    with (data_root / "objects.csv").open(encoding="utf-8", newline="") as f:
        objects = list(csv.DictReader(f))
    run = json.loads((data_root / "run.json").read_text(encoding="utf-8"))

    n_sequences = len(sequences)
    n_frames = sum(int(row["n_frames"]) for row in sequences)
    object_counts = Counter(int(row["n_objects"]) for row in sequences)
    rejections = sum(int(row["n_rejections"]) for row in sequences)
    widths = [
        float(row["band_hi_first"]) - float(row["band_lo_first"]) for row in objects
    ]
    stream_bytes = dict.fromkeys(_STREAMS, 0)
    with_bokeh = focused = 0
    for row in sequences:
        seq = data_root / "sequences" / row["seq_id"]
        for stream in _STREAMS:
            stream_bytes[stream] += sum(
                path.stat().st_size
                for path in (seq / stream).rglob("*")
                if path.is_file()
            )
        if (seq / "bokeh").is_dir():
            with_bokeh += 1
            focus = seq / "bokeh/focus.json"
            if focus.is_file():
                focused += (
                    json.loads(focus.read_text(encoding="utf-8"))["object"] is not None
                )

    return {
        "sequences": n_sequences,
        "frames": n_frames,
        "objects_per_sequence": {
            "counts": dict(sorted(object_counts.items())),
            "mean": sum(int(row["n_objects"]) for row in sequences) / n_sequences
            if n_sequences
            else None,
        },
        "depth_motion_share": sum(row["depth_motion"] == "true" for row in objects)
        / len(objects)
        if objects
        else None,
        "range_fallback_share": sum(row["range_fallback"] == "true" for row in objects)
        / len(objects)
        if objects
        else None,
        "rejections": {
            "total": rejections,
            "mean_per_sequence": rejections / n_sequences if n_sequences else None,
        },
        "foreground_reuse": _reuse([row["foreground"] for row in objects]),
        "background_reuse": _reuse([row["background"] for row in sequences]),
        "active_band_width_first": {
            "min": min(widths) if widths else None,
            "median": median(widths) if widths else None,
            "max": max(widths) if widths else None,
        },
        "object_focus_share": focused / with_bokeh if with_bokeh else None,
        "bytes_per_stream": {
            stream: {
                "total": total,
                "per_frame": total / n_frames if n_frames else None,
            }
            for stream, total in stream_bytes.items()
        },
        "run": run,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        stats = dataset_stats(args.data_root)
    except ValueError as exc:
        parser.error(str(exc))
    text = json.dumps(stats, indent=2) + "\n"
    print(text, end="")
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
