"""Visualize depth maps with proper normalization and colormap.

This script visualizes depth maps from depth_pro or depth_anything directories.

Input structure:
    data/depth_pro/           (or data/depth_anything/)
    ├── 0000/
    │   ├── 000.png
    │   ├── 001.png
    │   └── ...
    ├── 0001/
    └── ...

Output structure (parallel _viz directory):
    data/depth_pro_viz/       (or data/depth_anything_viz/)
    ├── 0000/
    │   ├── 000.png (colorized)
    │   ├── 001.png
    │   ├── depth_grid_turbo.png
    │   └── ...
    ├── 0001/
    └── ...

Usage:
    # Visualize all sequences in depth_pro -> depth_pro_viz
    python src/data/visualize_depth.py --input data/depth_pro --all-dirs

    # Visualize all sequences in depth_anything -> depth_anything_viz
    python src/data/visualize_depth.py --input data/depth_anything --all-dirs

    # Visualize a single sequence with custom output
    python src/data/visualize_depth.py --input data/depth_pro/0000 --output data/my_viz/0000

    # Use a different colormap
    python src/data/visualize_depth.py --input data/depth_pro --all-dirs --colormap viridis
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


def visualize_depth_maps(
    input_dir: str | Path,
    output_dir: str | Path,
    colormap: str = "turbo",
    save_individual: bool = True,
    create_grid: bool = True,
) -> None:
    """Visualize depth maps with proper normalization.

    Args:
        input_dir: Directory containing depth map PNG files.
        output_dir: Directory to save visualized images.
        colormap: Matplotlib colormap to use (e.g., 'turbo', 'viridis', 'plasma', 'magma').
        save_individual: Save each depth map as individual PNG.
        create_grid: Create a grid visualization of all depth maps.
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    output_path.mkdir(parents=True, exist_ok=True)

    # Get all PNG files (depth maps)
    png_files = sorted(input_path.glob("*.png"))

    if not png_files:
        print(f"No PNG files found in {input_path}")
        return

    print(f"Found {len(png_files)} depth map files in {input_dir}")

    depth_maps = []
    for png_file in png_files:
        # Load depth map
        img = Image.open(png_file)
        depth = np.array(img)

        # Convert to grayscale if multi-channel
        if len(depth.shape) == 3:
            depth = depth[:, :, 0]

        depth_maps.append((png_file.stem, depth))

        print(
            f"  {png_file.name}: shape={depth.shape}, min={depth.min():.2f}, max={depth.max():.2f}",
        )

    # Find global min/max for consistent normalization across all images
    all_depths = np.concatenate([d.flatten() for _, d in depth_maps])
    global_min, global_max = all_depths.min(), all_depths.max()
    print(f"\nGlobal range: [{global_min:.2f}, {global_max:.2f}]")

    # Save individual visualizations
    if save_individual:
        print(f"\nSaving individual visualizations to {output_path}/")
        for name, depth in depth_maps:
            # Normalize to 0-1 range
            if (global_max - global_min) > 0:
                depth_norm = (depth - global_min) / (global_max - global_min)
            else:
                depth_norm = np.zeros_like(depth, dtype=float)

            # Apply colormap
            cmap = plt.get_cmap(colormap)
            depth_colored = cmap(depth_norm)

            # Save as PNG (convert to uint8)
            depth_uint8 = (depth_colored[:, :, :3] * 255).astype(np.uint8)
            output_file = output_path / f"{name}.png"
            plt.imsave(str(output_file), depth_uint8)
            print(f"  Saved: {output_file.name}")

    # Create grid visualization
    if create_grid and len(depth_maps) > 0:
        n_images = len(depth_maps)
        cols = min(5, n_images)
        rows = (n_images + cols - 1) // cols

        fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows))
        if rows == 1 and cols == 1:
            axes = np.array([[axes]])
        elif rows == 1:
            axes = axes.reshape(1, -1)
        elif cols == 1:
            axes = axes.reshape(-1, 1)

        for idx, (name, depth) in enumerate(depth_maps):
            row, col = idx // cols, idx % cols
            ax = axes[row, col]

            # Normalize
            if (global_max - global_min) > 0:
                depth_norm = (depth - global_min) / (global_max - global_min)
            else:
                depth_norm = np.zeros_like(depth, dtype=float)

            ax.imshow(depth_norm, cmap=colormap, vmin=0, vmax=1)
            ax.set_title(f"{name}", fontsize=10)
            ax.axis("off")

        # Hide empty subplots
        for idx in range(n_images, rows * cols):
            row, col = idx // cols, idx % cols
            axes[row, col].axis("off")

        plt.suptitle("Depth Maps Visualization", fontsize=14)
        plt.tight_layout()

        grid_file = output_path / f"depth_grid_{colormap}.png"
        plt.savefig(str(grid_file), dpi=150, bbox_inches="tight")
        plt.close()
        print(f"\nSaved grid visualization: {grid_file}")


def get_viz_output_dir(input_dir: Path) -> Path:
    """Generate the visualization output directory path.

    Appends '_viz' to the input directory name.
    Example: data/depth_pro -> data/depth_pro_viz

    Args:
        input_dir: Input base directory.

    Returns:
        Output directory path with '_viz' suffix.
    """
    return input_dir.parent / f"{input_dir.name}_viz"


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Visualize depth maps with colormap",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Visualize all sequences in depth_pro -> depth_pro_viz
    python src/data/visualize_depth.py --input data/depth_pro --all-dirs

    # Visualize all sequences in depth_anything -> depth_anything_viz
    python src/data/visualize_depth.py --input data/depth_anything --all-dirs

    # Visualize a single sequence with custom output
    python src/data/visualize_depth.py --input data/depth_pro/0000 --output data/my_viz/0000

    # Use a different colormap
    python src/data/visualize_depth.py --input data/depth_pro --all-dirs --colormap viridis
        """,
    )

    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=Path("data/depth_pro"),
        help="Input directory (base dir with --all-dirs, or sequence dir)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output directory for visualizations (default: input_viz for --all-dirs)",
    )
    parser.add_argument(
        "--colormap",
        "-c",
        type=str,
        default="turbo",
        choices=["turbo", "viridis", "plasma", "magma", "inferno", "cividis", "gray"],
        help="Colormap to use for visualization",
    )
    parser.add_argument(
        "--all-dirs",
        action="store_true",
        help="Process all subdirectories in the input directory",
    )

    args = parser.parse_args()

    if args.all_dirs:
        # Process all subdirectories in the input directory
        if not args.input.exists():
            print(f"Error: {args.input} does not exist")
            return

        subdirs = sorted([d for d in args.input.iterdir() if d.is_dir()])
        if not subdirs:
            print(f"No subdirectories found in {args.input}")
            return

        # Determine output base directory
        if args.output is None:
            output_base = get_viz_output_dir(args.input)
        else:
            output_base = args.output

        print(f"Processing {len(subdirs)} sequences")
        print(f"Input:  {args.input}")
        print(f"Output: {output_base}")

        for subdir in subdirs:
            if subdir.name.startswith("."):
                continue

            print(f"\n{'=' * 60}")
            print(f"Processing: {subdir.name}")
            print(f"{'=' * 60}")

            visualize_depth_maps(
                input_dir=subdir,
                output_dir=output_base / subdir.name,
                colormap=args.colormap,
            )

        print(f"\n{'=' * 60}")
        print("All sequences processed successfully!")
        print(f"{'=' * 60}")
    else:
        # Process single directory
        if args.output is None:
            print("Error: --output is required when not using --all-dirs")
            return

        visualize_depth_maps(
            input_dir=args.input,
            output_dir=args.output,
            colormap=args.colormap,
        )


if __name__ == "__main__":
    main()
