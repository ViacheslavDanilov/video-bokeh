#!/usr/bin/env python3
"""Render sequences' bokeh with Dr.Bokeh's layer renderer, from our own layers.

Runs inside ``comparison/envs/render`` (see ``comparison/README.md``), not in the backend's
environment. It skips every sequence under ``--data-root`` that was not written with
``--layers`` or holds no ``bokeh/focus.json``. For each of the others, it renders every frame
from the same layers, focus disparity and strength as our layered renderer did, and writes

    <sequence>/bokeh_drbokeh/<frame>.png   RGB uint8, the sequence's size
    <sequence>/bokeh_drbokeh/run.json      the settings, so the two renders compare like for like

Dr.Bokeh's renderer takes a list of layers, nearest first, each with color, alpha and
disparity per pixel. Ours come from ``layers/`` and ``alpha/``, the background last and
opaque. Strength is Dr.Bokeh's ``K``, the blur radius in pixels at one unit of disparity from
the focus, so it is our strength scaled to the frame's width. Colors go through the same
power of 2.2 around the render that Dr.Bokeh's own entry script applies.

Usage:
    comparison/envs/render/bin/python comparison/run_drbokeh.py --data-root data/synth_dev
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import torch
from common import (
    GAMMA,
    REFERENCE_WIDTH,
    REPO,
    LayeredFrame,
    focus_record,
    frames_with_focus,
    renderable_sequences,
    save_rgb,
    write_settings,
)
from scipy import ndimage

sys.path.insert(
    0, str(REPO / "comparison" / "third_party" / "drbokeh" / "app" / "cuda-src")
)
sys.path.insert(
    0,
    str(
        REPO / "comparison" / "third_party" / "drbokeh" / "app" / "Render" / "DScatter"
    ),
)

from scatter import Multi_Layer_Renderer  # noqa: E402


def _extend_disparity(disparity: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """A layer's disparity defined everywhere, as Dr.Bokeh expects it.

    Our object layers store disparity only under their alpha and zero elsewhere. The renderer
    reads the disparity of every pixel, including those with no alpha, to size the blur at an
    edge, and a zero would read as a pixel far behind the focus. Each pixel outside takes the
    disparity of the nearest pixel under the alpha.
    """
    inside = alpha > 0
    if not inside.any():
        return disparity
    nearest = ndimage.distance_transform_edt(
        ~inside, return_distances=False, return_indices=True
    )
    return disparity[nearest[0], nearest[1]]


def _layers_near_to_far(frame: LayeredFrame) -> list[np.ndarray]:
    """One ``(H, W, 5)`` array per layer, red, green, blue, alpha, disparity, nearest first."""
    layers = []
    for page in reversed(list(frame.paint_order)):
        color = frame.object_rgbs[page].transpose(1, 2, 0)
        alpha = frame.object_alphas[page]
        disparity = _extend_disparity(frame.object_disparities[page], alpha)
        layers.append(
            np.concatenate([color, alpha[..., None], disparity[..., None]], axis=2)
        )
    color = frame.background.transpose(1, 2, 0)
    alpha = np.ones(color.shape[:2] + (1,), dtype=np.float32)
    layers.append(
        np.concatenate(
            [color, alpha, frame.background_disparity.transpose(1, 2, 0)], axis=2
        )
    )
    return layers


def _lens_size(layers: list[np.ndarray], zf: float, k: float) -> int:
    """The smallest odd kernel that holds the largest radius any layer's pixel asks for."""
    widest = max(
        float(np.abs(layer[..., 4] - zf)[layer[..., 3] > 0].max(initial=0.0))
        for layer in layers
    )
    return 2 * math.ceil(k * widest) + 3


def render_sequence(seq: Path, device: torch.device) -> None:
    strength = float(focus_record(seq)["strength"])
    out = seq / "bokeh_drbokeh"
    renderers: dict[int, Multi_Layer_Renderer] = {}
    for name, zf, frame in frames_with_focus(seq):
        layers = _layers_near_to_far(frame)
        width = layers[0].shape[1]
        k = strength * width / REFERENCE_WIDTH
        lens = _lens_size(layers, zf, k)
        if lens not in renderers:
            renderers[lens] = Multi_Layer_Renderer(lens).to(device)
        gamma = [
            np.concatenate([layer[..., :3] ** GAMMA, layer[..., 3:]], axis=2)
            for layer in layers
        ]
        with torch.no_grad():
            blur = renderers[lens].inference(gamma, k, zf)
        save_rgb(out, name, np.clip(blur, 0.0, 1.0) ** (1.0 / GAMMA))
    write_settings(out, "Dr.Bokeh", seq, gamma=GAMMA)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--seqs", default=None, help="comma-separated sequence ids")
    args = parser.parse_args(argv)
    names = args.seqs.split(",") if args.seqs else None
    device = torch.device("cuda:0")
    for seq in renderable_sequences(args.data_root, names):
        render_sequence(seq, device)
        print(f"  {seq.name}: bokeh_drbokeh written", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
