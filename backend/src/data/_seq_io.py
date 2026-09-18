"""Sequence-directory I/O shared across data scripts."""

from __future__ import annotations

from pathlib import Path


def list_sequences(root: Path, seqs: list[str] | None) -> list[Path]:
    """Return sequence subdirectories under ``<root>/sequences``, optionally filtered."""
    seq_root = root / "sequences"
    if not seq_root.exists():
        raise FileNotFoundError(f"sequences dir missing: {seq_root}")
    dirs = sorted(p for p in seq_root.iterdir() if p.is_dir())
    if seqs is None:
        return dirs
    wanted = set(seqs)
    picked = [p for p in dirs if p.name in wanted]
    missing = wanted - {p.name for p in picked}
    if missing:
        raise SystemExit(f"sequences not found under {seq_root}: {sorted(missing)}")
    return picked
