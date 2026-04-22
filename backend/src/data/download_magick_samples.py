#!/usr/bin/env python3
"""Download a sample of MAGICK images into a dev-dataset mirror.

Mirrors the upstream HuggingFace layout so the dev set is a drop-in substitute
for the full dataset:

    <output>/
    ├── metadata.csv          # same columns as the source metadata
    └── images/
        ├── <pp>/             # first two chars of page_id
        │   └── <page_id>.png
        └── ...

Source URL pattern:
    https://huggingface.co/datasets/OneOverZero/MAGICK/resolve/main/images/<pp>/<page_id>.png

Usage:
    uv run python -m data.download_magick_samples \
        --metadata backend/data/magick_metadata.csv \
        --output   backend/data/magick_dev \
        --count    20 \
        --seed     0

    # Include auto-picked rows too
    uv run python -m data.download_magick_samples ... --picked any

    # Only auto-picked rows
    uv run python -m data.download_magick_samples ... --picked auto
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

import httpx

HF_BASE = "https://huggingface.co/datasets/OneOverZero/MAGICK/resolve/main/images"


def page_id_to_url(page_id: str) -> str:
    return f"{HF_BASE}/{page_id[:2]}/{page_id}.png"


def image_path(root: Path, page_id: str) -> Path:
    return root / "images" / page_id[:2] / f"{page_id}.png"


def read_metadata(metadata_csv: Path) -> tuple[list[str], list[dict[str, str]]]:
    with metadata_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"{metadata_csv}: missing header row")
        fieldnames = list(reader.fieldnames)
        rows = [dict(r) for r in reader if r.get("page_id", "").strip()]
    return fieldnames, rows


def download_one(client: httpx.Client, page_id: str, dest: Path) -> bool:
    url = page_id_to_url(page_id)
    try:
        resp = client.get(url, follow_redirects=True, timeout=60)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"  FAIL {page_id}: {exc}", file=sys.stderr)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument(
        "--picked",
        default="hand",
        help="Keep only rows where the `picked` column equals this value. "
        'Pass "any" to disable filtering. Default: "hand".',
    )
    args = parser.parse_args()

    fieldnames, rows = read_metadata(args.metadata)
    if not rows:
        print(f"No rows in {args.metadata}", file=sys.stderr)
        return 1

    if args.picked != "any":
        if "picked" not in fieldnames:
            print(
                f"  WARN {args.metadata} has no `picked` column; --picked ignored",
                file=sys.stderr,
            )
        else:
            before = len(rows)
            rows = [r for r in rows if r.get("picked", "").strip() == args.picked]
            print(f"  Filter: picked == {args.picked!r} → {len(rows)}/{before} rows")
            if not rows:
                print(f"No rows match --picked {args.picked!r}", file=sys.stderr)
                return 1

    rng = random.Random(args.seed)
    sample = rng.sample(rows, min(args.count, len(rows)))

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "images").mkdir(parents=True, exist_ok=True)

    downloaded: list[dict[str, str]] = []
    with httpx.Client() as client:
        for row in sample:
            page_id = row["page_id"].strip()
            dest = image_path(args.output, page_id)
            if dest.exists():
                print(f"  SKIP {page_id} (exists)")
                downloaded.append(row)
                continue
            if download_one(client, page_id, dest):
                print(f"  OK   {page_id}")
                downloaded.append(row)

    metadata_out = args.output / "metadata.csv"
    with metadata_out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in downloaded:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    print(
        f"\nDownloaded {len(downloaded)}/{len(sample)} images to {args.output / 'images'}",
    )
    print(f"Metadata: {metadata_out}")
    return 0 if downloaded else 2


if __name__ == "__main__":
    raise SystemExit(main())
