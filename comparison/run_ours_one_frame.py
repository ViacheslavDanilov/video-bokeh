#!/usr/bin/env python3
"""Render sequences' bokeh with our renderer from the all-in-focus frame alone, as one layer.

Runs inside ``comparison/envs/render`` (see ``comparison/README.md``). Our renderer blurs each
layer on its own and composites the blurred layers, so an object in front thins out at its edges
and shows the background behind it whole. This adapter takes that away and keeps everything
else: the frame is the only layer, the background, and its disparity is the composite disparity
map. The renderer, its disk kernel, radius binning, gamma and strength are the ones that
rendered ``bokeh/``, and so is the focus, read from ``bokeh/focus.json``. What is behind an
object is gone from the frame, as it is from the input of a single-image method such as
BokehMe. The difference to ``bokeh/`` is therefore the layers and nothing else.

For every sequence under ``--data-root`` that holds layers and ``bokeh/focus.json`` it writes

    <sequence>/bokeh_ours_one_frame/<frame>.png

Usage:
    comparison/envs/render/bin/python comparison/run_ours_one_frame.py --data-root data/synth_dev
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
from common import (
    GAMMA,
    composite_frame,
    focus_record,
    frame_names,
    renderable_sequences,
    save_rgb,
    write_settings,
)

from video_bokeh.layered import bokeh_device, render_bokeh

STREAM = "bokeh_ours_one_frame"


def render_frame(
    rgb: np.ndarray,
    disparity: np.ndarray,
    focus: float,
    strength: float,
    device: torch.device | None = None,
) -> np.ndarray:
    """One frame's bokeh, ``(H, W, 3)`` in ``[0, 1]``, from its color and composite disparity."""
    device = device or torch.device("cpu")
    height, width = rgb.shape[:2]
    out = render_bokeh(
        background=torch.from_numpy(rgb).permute(2, 0, 1)[None].to(device),
        background_disparity=torch.from_numpy(disparity.astype(np.float32))[
            None, None
        ].to(device),
        object_rgbs=torch.zeros(1, 0, 3, height, width, device=device),
        object_alphas=torch.zeros(1, 0, height, width, device=device),
        object_disparities=torch.zeros(1, 0, height, width, device=device),
        paint_order=torch.zeros(1, 0, dtype=torch.long, device=device),
        focus_disparity=torch.tensor([focus], device=device),
        strength=strength,
        gamma=GAMMA,
    )
    return out[0].permute(1, 2, 0).cpu().numpy()


def render_sequence(seq: Path, device: torch.device) -> None:
    record = focus_record(seq)
    strength = float(record["strength"])
    for name, zf in zip(frame_names(seq), record["zf"], strict=True):
        rgb, disparity = composite_frame(seq, name)
        save_rgb(seq / STREAM, name, render_frame(rgb, disparity, zf, strength, device))
    write_settings(
        seq / STREAM, "Ours, on the all-in-focus frame alone", seq, gamma=GAMMA
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--seqs", default=None, help="comma-separated sequence ids")
    args = parser.parse_args(argv)
    names = args.seqs.split(",") if args.seqs else None
    device = bokeh_device()
    for seq in renderable_sequences(args.data_root, names):
        render_sequence(seq, device)
        print(f"  {seq.name}: {STREAM} written", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
