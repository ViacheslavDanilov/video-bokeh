#!/usr/bin/env python3
"""Score one bokeh stream against another over written sequences.

Both streams are read from each sequence directory, ``bokeh/`` for ours by default and
``bokeh_<method>/`` for a method run by ``comparison/run_<method>.py``. For every frame it
reports the peak signal-to-noise ratio and the mean absolute difference, in 8-bit gray
levels, over the whole frame and over a band around the object edges, where layered and
single-layer renderers part. The band is every pixel within ``--band`` pixels of an edge of
any object's alpha mask. The result is written to ``<data-root>/comparison_<method>.json``.

Usage:
    comparison/envs/render/bin/python comparison/score.py --data-root data/synth_dev --method drbokeh
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend" / "src"))

from video_bokeh.core._seq_io import frame_names, list_sequences  # noqa: E402
from video_bokeh.core._streams import read_alpha_tiff  # noqa: E402

#: An alpha that changes by more than this between neighbors marks an edge.
EDGE_STEP = 0.02


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    """Peak signal-to-noise ratio of two 8-bit images, in dB; infinite when they match."""
    error = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    return float("inf") if error == 0 else float(10 * np.log10(255.0**2 / error))


def edge_band(alphas: list[np.ndarray], width: int) -> np.ndarray:
    """Pixels within ``width`` pixels of an edge of any alpha mask, as a boolean array."""
    edges = np.zeros(alphas[0].shape, dtype=bool)
    for alpha in alphas:
        step_y = np.abs(np.diff(alpha, axis=0, prepend=alpha[:1]))
        step_x = np.abs(np.diff(alpha, axis=1, prepend=alpha[:, :1]))
        edges |= (step_y > EDGE_STEP) | (step_x > EDGE_STEP)
    return ndimage.binary_dilation(edges, iterations=width) if edges.any() else edges


def _read(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))


def score_sequence(seq: Path, reference: str, method: str, band: int) -> dict:
    frames = []
    for name in frame_names(seq):
        ours = _read(seq / reference / name)
        theirs = _read(seq / f"bokeh_{method}" / name)
        alphas = read_alpha_tiff(seq / "alpha" / f"{Path(name).stem}.tif")
        near = edge_band(alphas, band)
        diff = np.abs(ours.astype(np.float64) - theirs.astype(np.float64))
        frames.append(
            {
                "frame": name,
                "psnr": psnr(ours, theirs),
                "mae": float(diff.mean()),
                "band_share": float(near.mean()),
                "band_psnr": psnr(ours[near], theirs[near]) if near.any() else None,
                "band_mae": float(diff[near].mean()) if near.any() else None,
            }
        )

    def mean(key: str) -> float | None:
        values = [f[key] for f in frames if f[key] is not None and np.isfinite(f[key])]
        return float(np.mean(values)) if values else None

    return {
        "sequence": seq.name,
        "frames": frames,
        "mean": {k: mean(k) for k in ("psnr", "mae", "band_psnr", "band_mae")},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument(
        "--method", required=True, help="the stream bokeh_<method> to score"
    )
    parser.add_argument(
        "--reference", default="bokeh", help="the stream to score against"
    )
    parser.add_argument(
        "--band", type=int, default=16, help="edge band width in pixels"
    )
    parser.add_argument("--seqs", default=None, help="comma-separated sequence ids")
    args = parser.parse_args(argv)
    names = args.seqs.split(",") if args.seqs else None
    results = [
        score_sequence(seq, args.reference, args.method, args.band)
        for seq in list_sequences(args.data_root, names)
    ]
    record = {
        "method": args.method,
        "reference": args.reference,
        "band": args.band,
        "sequences": results,
    }
    out = args.data_root / f"comparison_{args.method}.json"
    out.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    for result in results:
        m = result["mean"]
        print(
            f"  {result['sequence']}: PSNR {m['psnr']:.2f} dB, band {m['band_psnr']:.2f} dB, "
            f"MAE {m['mae']:.2f}, band MAE {m['band_mae']:.2f}"
        )
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
