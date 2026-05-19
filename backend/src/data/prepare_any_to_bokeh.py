#!/usr/bin/env python3
"""Prepare synthetic sequences for the vendored any-to-bokeh inference code.

Reads our sequence layout:

    <data-root>/sequences/<id>/all_in_focus/*.png
    <data-root>/sequences/<id>/alpha/*.png
    <data-root>/sequences/<id>/disparity/*.tif

and writes any-to-bokeh-compatible inputs:

    <a2b-root>/demo_dataset/<dataset-name>/videos/<id>/01.png
    <a2b-root>/demo_dataset/<dataset-name>/disp/<id>/01_zf_0.123456.png
    <a2b-root>/csv_file/<dataset-name>.csv

Frame names are intentionally 1-based and zero-padded like our sequence
frames, unlike the vendored demo assets that start at 0. any-to-bokeh parses
frame order from the numeric filename prefix.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

from data._seq_io import list_sequences


def _parse_seqs(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _numeric_stem(path: Path) -> int:
    return int(path.stem.split("_", maxsplit=1)[0])


def _list_png_frames(path: Path) -> list[Path]:
    if not path.exists():
        raise FileNotFoundError(f"frame directory missing: {path}")
    return sorted(path.glob("*.png"), key=_numeric_stem)


def _list_tif_frames(path: Path) -> list[Path]:
    if not path.exists():
        raise FileNotFoundError(f"disparity directory missing: {path}")
    return sorted(path.glob("*.tif"), key=_numeric_stem)


def _to_uint8_disparities(arrs: list[np.ndarray]) -> list[np.ndarray]:
    stack = np.asarray(arrs, dtype=np.float32)
    lo = float(np.nanmin(stack))
    hi = float(np.nanmax(stack))
    if lo >= 0.0 and hi <= 1.0:
        return [(arr.clip(0.0, 1.0) * 255.0).round().astype(np.uint8) for arr in arrs]

    scale = max(hi - lo, 1e-6)
    return [
        ((arr - lo) / scale * 255.0).clip(0, 255).round().astype(np.uint8)
        for arr in arrs
    ]


def _load_focus_mask(alpha_path: Path | None, shape: tuple[int, int]) -> np.ndarray:
    if alpha_path is None or not alpha_path.exists():
        return np.ones(shape, dtype=bool)
    alpha = np.asarray(Image.open(alpha_path).convert("L"), dtype=np.uint8)
    if alpha.shape != shape:
        raise ValueError(
            f"alpha shape {alpha.shape} does not match disparity shape {shape}: {alpha_path}",
        )
    mask = alpha > 127
    if not mask.any():
        return np.ones(shape, dtype=bool)
    return mask


def _relative_to_a2b(path: Path, a2b_root: Path) -> str:
    return path.resolve().relative_to(a2b_root.resolve()).as_posix()


def _write_sequence(
    seq_dir: Path,
    out_video_dir: Path,
    out_disp_dir: Path,
    use_alpha_focus: bool,
) -> int:
    image_paths = _list_png_frames(seq_dir / "all_in_focus")
    disparity_paths = _list_tif_frames(seq_dir / "disparity")
    alpha_paths = (
        _list_png_frames(seq_dir / "alpha") if (seq_dir / "alpha").exists() else []
    )

    if len(image_paths) != len(disparity_paths):
        raise ValueError(
            f"{seq_dir.name}: {len(image_paths)} all_in_focus frames but "
            f"{len(disparity_paths)} disparity frames",
        )
    if use_alpha_focus and alpha_paths and len(alpha_paths) != len(image_paths):
        raise ValueError(
            f"{seq_dir.name}: {len(image_paths)} all_in_focus frames but "
            f"{len(alpha_paths)} alpha frames",
        )

    out_video_dir.mkdir(parents=True, exist_ok=True)
    out_disp_dir.mkdir(parents=True, exist_ok=True)

    raw_disps = [tifffile.imread(path).astype(np.float32) for path in disparity_paths]
    disp_pngs = _to_uint8_disparities(raw_disps)
    digits = max(2, len(str(len(image_paths))))

    for idx, (image_path, disp_u8) in enumerate(
        zip(image_paths, disp_pngs, strict=True),
        start=1,
    ):
        frame_stem = f"{idx:0{digits}d}"
        Image.open(image_path).convert("RGB").save(
            out_video_dir / f"{frame_stem}.png",
            compress_level=6,
        )

        alpha_path = alpha_paths[idx - 1] if use_alpha_focus and alpha_paths else None
        mask = _load_focus_mask(alpha_path, disp_u8.shape)
        zf = float(disp_u8[mask].mean() / 255.0)
        Image.fromarray(disp_u8, mode="L").save(
            out_disp_dir / f"{frame_stem}_zf_{zf:.6f}.png",
            compress_level=6,
        )

    return len(image_paths)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="dataset root containing sequences/ (e.g. data/synth_dev_new)",
    )
    parser.add_argument(
        "--a2b-root",
        type=Path,
        default=Path("third_party/any-to-bokeh"),
        help="vendored any-to-bokeh root, relative to backend/ by default",
    )
    parser.add_argument(
        "--dataset-name",
        default=None,
        help="name under demo_dataset/ and csv_file/. Default: data-root basename.",
    )
    parser.add_argument("--k", default="16", help="blur strength column for CSV")
    parser.add_argument(
        "--seqs",
        type=_parse_seqs,
        default=None,
        help="Comma-separated sequence ids (e.g. '0001,0003'). Default: all.",
    )
    parser.add_argument(
        "--focus",
        choices=("alpha", "full"),
        default="alpha",
        help="how to compute zf in disparity filenames. Default: alpha mask mean.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    dataset_name = args.dataset_name or args.data_root.name
    a2b_root = args.a2b_root
    out_root = a2b_root / "demo_dataset" / dataset_name
    videos_root = out_root / "videos"
    disp_root = out_root / "disp"
    csv_path = a2b_root / "csv_file" / f"{dataset_name}.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    seq_dirs = list_sequences(args.data_root, args.seqs)
    if not seq_dirs:
        raise SystemExit(
            f"no sequences to process under {args.data_root / 'sequences'}",
        )

    rows: list[list[str]] = []
    for seq_dir in seq_dirs:
        out_video_dir = videos_root / seq_dir.name
        out_disp_dir = disp_root / seq_dir.name
        count = _write_sequence(
            seq_dir=seq_dir,
            out_video_dir=out_video_dir,
            out_disp_dir=out_disp_dir,
            use_alpha_focus=args.focus == "alpha",
        )
        rows.append(
            [
                _relative_to_a2b(out_video_dir, a2b_root),
                _relative_to_a2b(out_disp_dir, a2b_root),
                str(args.k),
            ],
        )
        print(f"  {seq_dir.name}: wrote {count} frame(s)")

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["aif_folder", "disp_folder", "k"])
        writer.writerows(rows)

    print(f"\nDone. CSV: {csv_path}")
    print(f"Run any-to-bokeh from {a2b_root}:")
    print(f"  python test/inference_demo.py --val_csv_path csv_file/{dataset_name}.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
