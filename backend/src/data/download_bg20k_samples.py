#!/usr/bin/env python3
"""Download a sample of BG-20k background images into a dev-dataset mirror.

Mirrors a subset of the upstream Kaggle layout so the dev set is a drop-in
substitute for the full dataset:

    <output>/
    ├── metadata.csv          # filename, split
    └── images/
        ├── train/
        │   └── <name>.jpg
        └── testval/
            └── <name>.jpg

Source: https://www.kaggle.com/datasets/nguyenquocdungk16hl/bg-20o
Requires Kaggle credentials at ~/.kaggle/kaggle.json (or KAGGLE_USERNAME /
KAGGLE_KEY env vars).

Usage:
    uv run python -m data.download_bg20k_samples \
        --output backend/data/bg20k_dev \
        --count  20 \
        --seed   0

    # Only train or only testval images
    uv run python -m data.download_bg20k_samples ... --split train
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

from kaggle.api.kaggle_api_extended import KaggleApi

DEFAULT_DATASET = "nguyenquocdungk16hl/bg-20o"
# Files inside the Kaggle archive are rooted at "1/BG-20k/..."; images live
# under the "train" and "testval" subfolders.
ROOT_PREFIX = "1/BG-20k/"
IMAGE_SPLITS = ("train", "testval")


def list_all_files(api: KaggleApi, dataset: str) -> list[str]:
    names: list[str] = []
    token: str | None = None
    while True:
        resp = api.dataset_list_files(
            dataset,
            page_size=1000,
            page_token=token,
        )
        names.extend(f.name for f in resp.files)
        token = resp.next_page_token
        if not token:
            break
    return names


def classify(name: str) -> tuple[str, str] | None:
    """Return (split, basename) for an image file, or None to skip."""
    if not name.startswith(ROOT_PREFIX):
        return None
    rel = name[len(ROOT_PREFIX) :]
    head, _, tail = rel.partition("/")
    if head not in IMAGE_SPLITS or not tail:
        return None
    if not tail.lower().endswith((".jpg", ".jpeg", ".png")):
        return None
    return head, tail


def download_one(api: KaggleApi, dataset: str, remote: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        api.dataset_download_file(
            dataset,
            file_name=remote,
            path=str(dest.parent),
            force=True,
            quiet=True,
        )
    except Exception as exc:  # noqa: BLE001 - surface any kaggle error
        print(f"  FAIL {remote}: {exc}", file=sys.stderr)
        return False

    # Kaggle saves the file under its basename, optionally with a .zip suffix
    # for large files. Normalize to `dest`.
    basename = Path(remote).name
    candidate = dest.parent / basename
    zipped = dest.parent / f"{basename}.zip"
    if zipped.exists():
        import zipfile

        with zipfile.ZipFile(zipped) as zf:
            zf.extract(basename, path=dest.parent)
        zipped.unlink()
    if candidate != dest and candidate.exists():
        candidate.rename(dest)
    return dest.exists()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument(
        "--split",
        choices=("any", *IMAGE_SPLITS),
        default="any",
        help='Restrict to a single split. Default: "any".',
    )
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help=f"Kaggle dataset slug. Default: {DEFAULT_DATASET!r}.",
    )
    args = parser.parse_args()

    api = KaggleApi()
    api.authenticate()

    print(f"Listing files in {args.dataset} ...")
    all_names = list_all_files(api, args.dataset)
    entries: list[tuple[str, str, str]] = []  # (split, basename, remote)
    for name in all_names:
        cls = classify(name)
        if cls is None:
            continue
        split, basename = cls
        if args.split != "any" and split != args.split:
            continue
        entries.append((split, basename, name))

    if not entries:
        print(f"No images match filter (split={args.split!r})", file=sys.stderr)
        return 1
    print(f"  Found {len(entries)} candidate images")

    rng = random.Random(args.seed)
    sample = rng.sample(entries, min(args.count, len(entries)))

    (args.output / "images").mkdir(parents=True, exist_ok=True)

    downloaded: list[tuple[str, str]] = []  # (basename, split)
    for split, basename, remote in sample:
        dest = args.output / "images" / split / basename
        if dest.exists():
            print(f"  SKIP {split}/{basename} (exists)")
            downloaded.append((basename, split))
            continue
        if download_one(api, args.dataset, remote, dest):
            print(f"  OK   {split}/{basename}")
            downloaded.append((basename, split))

    metadata_out = args.output / "metadata.csv"
    with metadata_out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "split"])
        for basename, split in sorted(downloaded):
            writer.writerow([basename, split])

    print(
        f"\nDownloaded {len(downloaded)}/{len(sample)} images to {args.output / 'images'}",
    )
    print(f"Metadata: {metadata_out}")
    return 0 if downloaded else 2


if __name__ == "__main__":
    raise SystemExit(main())
