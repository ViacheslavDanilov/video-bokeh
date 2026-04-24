#!/usr/bin/env python3
"""Download the BG-20k dataset via kagglehub.

Source: https://www.kaggle.com/datasets/nguyenquocdungk16hl/bg-20o

Usage:
    uv run python -m data.download_bg20k --output backend/data/bg20k
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

KAGGLE_DATASET = "nguyenquocdungk16hl/bg-20o"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["KAGGLEHUB_CACHE"] = str(args.output.resolve())

    import kagglehub  # noqa: E402 — must be imported after KAGGLEHUB_CACHE is set

    path = kagglehub.dataset_download(KAGGLE_DATASET)
    print(f"Path to dataset files: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
