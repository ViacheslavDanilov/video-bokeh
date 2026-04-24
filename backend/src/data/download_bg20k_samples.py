#!/usr/bin/env python3
"""Download the BG-20k dataset via kagglehub.

Source: https://www.kaggle.com/datasets/nguyenquocdungk16hl/bg-20o

Usage:
    uv run python -m data.download_bg20k_samples --output backend/data/bg20k
"""

import argparse
import os
from pathlib import Path

import kagglehub

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()

args.output.mkdir(parents=True, exist_ok=True)
os.environ["KAGGLEHUB_CACHE"] = str(args.output.resolve())

path = kagglehub.dataset_download("nguyenquocdungk16hl/bg-20o")
print("Path to dataset files:", path)
