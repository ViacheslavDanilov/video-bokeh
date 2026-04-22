#!/usr/bin/env python3
"""Convert TIFF depth maps to PNG format for depth_pro.

This script converts 32-bit TIFF depth maps to 8-bit grayscale PNG files.
The depth values are normalized across all images for consistent scaling.

Input structure (data/tiff):
    data/tiff/
    ├── 0000/
    │   ├── 000.tif
    │   ├── 001.tif
    │   └── ...
    ├── 0001/
    └── ...

Output structure (data/depth_pro):
    data/depth_pro/
    ├── 0000/
    │   ├── 000.png
    │   ├── 001.png
    │   └── ...
    ├── 0001/
    └── ...

Usage:
    # Convert a single sequence
    python src/data/convert_depth.py --input data/tiff/0000 --output data/depth_pro/0000

    # Convert all sequences (recommended)
    python src/data/convert_depth.py --all-dirs

    # Invert depth (closer = brighter)
    python src/data/convert_depth.py --all-dirs --invert
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

# Directory configuration
TIFF_DIR = Path("data/tiff")
DEPTH_PRO_DIR = Path("data/depth_pro2")


def convert_tiff_to_png(
    input_dir: str | Path,
    output_dir: str | Path,
    invert: bool = False,
) -> None:
    """Convert TIFF depth maps to 8-bit PNG format.

    Args:
        input_dir: Directory containing TIFF depth maps.
        output_dir: Output directory for PNG files.
        invert: If True, invert depth values (closer objects become brighter).
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    output_path.mkdir(parents=True, exist_ok=True)

    # Find all TIFF files
    tiff_files = sorted(input_path.glob("*.tif")) + sorted(input_path.glob("*.tiff"))

    if not tiff_files:
        print(f"No TIFF files found in {input_path}")
        return

    print(f"Found {len(tiff_files)} TIFF files in {input_path}")
    print(f"Output directory: {output_path}")

    # First pass: find global min/max for normalization
    global_min = float("inf")
    global_max = float("-inf")

    for tiff_file in tiff_files:
        depth = tifffile.imread(tiff_file)
        if depth.ndim == 3:
            depth = depth[:, :, 0]
        global_min = min(global_min, float(depth.min()))
        global_max = max(global_max, float(depth.max()))

    print(f"Depth range: [{global_min:.4f}, {global_max:.4f}]")

    # Second pass: convert each file
    for tiff_file in tiff_files:
        # Load depth map
        depth = tifffile.imread(tiff_file)

        # Handle multi-channel images
        if depth.ndim == 3:
            depth = depth[:, :, 0]

        # Normalize to 0-1 range
        if (global_max - global_min) > 0:
            depth_norm = (depth - global_min) / (global_max - global_min)
        else:
            depth_norm = np.zeros_like(depth)

        # Invert if requested (closer = brighter)
        if invert:
            depth_norm = 1.0 - depth_norm

        # Scale to 8-bit range
        depth_uint8 = (depth_norm * 255).astype(np.uint8)

        # Save as PNG
        output_file = output_path / f"{tiff_file.stem}.png"
        Image.fromarray(depth_uint8).save(output_file)

    print(f"Converted {len(tiff_files)} files to {output_path}")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Convert TIFF depth maps to 8-bit PNG format for depth_pro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Convert all sequences from data/tiff to data/depth_pro
    python src/data/convert_depth.py --all-dirs

    # Convert a single sequence
    python src/data/convert_depth.py -i data/tiff/0000 -o data/depth_pro/0000

    # Convert with inverted depth (closer = brighter)
    python src/data/convert_depth.py --all-dirs --invert
        """,
    )

    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=None,
        help="Input directory containing TIFF depth maps (e.g., data/tiff/0000)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output directory for PNG files (e.g., data/depth_pro/0000)",
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        help="Invert depth values (closer objects become brighter)",
    )
    parser.add_argument(
        "--all-dirs",
        action="store_true",
        help=f"Process all sequences: {TIFF_DIR}/* -> {DEPTH_PRO_DIR}/*",
    )

    args = parser.parse_args()

    if args.all_dirs:
        # Process all subdirectories in data/tiff
        if not TIFF_DIR.exists():
            print(f"Error: {TIFF_DIR} does not exist")
            return

        subdirs = sorted([d for d in TIFF_DIR.iterdir() if d.is_dir()])
        if not subdirs:
            print(f"No subdirectories found in {TIFF_DIR}")
            return

        print(f"Processing {len(subdirs)} sequences from {TIFF_DIR} to {DEPTH_PRO_DIR}")

        for subdir in subdirs:
            if subdir.name.startswith("."):
                continue

            print(f"\n{'=' * 60}")
            print(f"Processing: {subdir.name}")
            print(f"{'=' * 60}")

            convert_tiff_to_png(
                input_dir=subdir,
                output_dir=DEPTH_PRO_DIR / subdir.name,
                invert=args.invert,
            )

        print(f"\n{'=' * 60}")
        print("All sequences processed successfully!")
        print(f"{'=' * 60}")
    else:
        # Process single directory
        if args.input is None:
            parser.error("--input is required when not using --all-dirs")

        if args.output is None:
            # Default: replace 'tiff' with 'depth_pro' in path
            output = DEPTH_PRO_DIR / args.input.name
        else:
            output = args.output

        convert_tiff_to_png(
            input_dir=args.input,
            output_dir=output,
            invert=args.invert,
        )


if __name__ == "__main__":
    main()
