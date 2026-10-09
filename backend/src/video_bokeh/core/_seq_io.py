"""Sequence-directory I/O shared across data scripts."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from video_bokeh.core._streams import read_paint_order


def list_sequences(root: Path, seqs: list[str] | None) -> list[Path]:
    """Return sequence subdirectories under ``<root>/sequences``, optionally filtered.

    A name starting with a dot is skipped: the API generates a sequence under ``.tmp-*``
    beside the finished ones and renames it when it is whole.
    """
    seq_root = root / "sequences"
    if not seq_root.exists():
        raise FileNotFoundError(f"sequences dir missing: {seq_root}")
    dirs = sorted(
        p for p in seq_root.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    if seqs is None:
        return dirs
    wanted = set(seqs)
    picked = [p for p in dirs if p.name in wanted]
    missing = wanted - {p.name for p in picked}
    if missing:
        raise SystemExit(f"sequences not found under {seq_root}: {sorted(missing)}")
    return picked


def sequence_seed(seq_dir: Path) -> int | None:
    """The seed a sequence was generated from, where it is recorded.

    A sequence the API generated records it in its ``sequence.json``; a dataset records
    each sequence's in ``manifest.csv``, two levels up. None when neither says.
    """
    meta = seq_dir / "sequence.json"
    if meta.is_file():
        return int(json.loads(meta.read_text(encoding="utf-8"))["seed"])
    manifest = seq_dir.parent.parent / "manifest.csv"
    if manifest.is_file():
        with manifest.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("seq_id") == seq_dir.name:
                    return int(row["seed"])
    return None


def has_layers(seq_dir: Path) -> bool:
    """Whether a sequence holds a whole ``layers/`` stream: one paint order per frame.

    ``paint_order.json`` is written last, so a ``layers/`` without it, or with fewer
    orders than frames, was interrupted or belongs to another run.
    """
    orders = seq_dir / "layers" / "paint_order.json"
    if not orders.is_file():
        return False
    frames = len(list((seq_dir / "all_in_focus").glob("*.png")))
    return len(read_paint_order(orders)) == frames
