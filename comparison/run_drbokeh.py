#!/usr/bin/env python3
"""Render sequences' bokeh with Dr.Bokeh's layer renderer, from our own layers.

Runs inside ``comparison/envs/render`` (see ``comparison/README.md``), not in the backend's
environment. It skips every sequence under ``--data-root`` that was not written with
``--layers`` or holds no ``bokeh/focus.json``. For each of the others, it renders every frame
from the same layers, focus disparity and strength as our layered renderer did, and writes

    <sequence>/bokeh_drbokeh/<frame>.png   RGB uint8, the sequence's size
    <sequence>/bokeh_drbokeh/run.json      the settings, so the two renders compare like for like

or, with ``--composite gamma``, the same under ``bokeh_drbokeh_cg/``.

Dr.Bokeh's renderer takes a list of layers, nearest first, each with color, alpha and
disparity per pixel. Ours come from ``layers/`` and ``alpha/``, the background last and
opaque. Strength is Dr.Bokeh's ``K``, the blur radius in pixels at one unit of disparity from
the focus, so it is our strength scaled to the frame's width. Colors go through the same
power of 2.2 around the render that Dr.Bokeh's own entry script applies.

By default Dr.Bokeh composites the blurred layers in linear light, as it was published.
``--composite gamma`` scatters each layer with Dr.Bokeh's own kernel, in linear light as
before, then brings each layer's straight color back to gamma values and composites the layers
there, as Stage B and our renderer do.

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
    composite_near_to_far,
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


#: The stream each compositing space writes.
STREAMS = {"linear": "bokeh_drbokeh", "gamma": "bokeh_drbokeh_cg"}


def scatter_layers(
    renderer: Multi_Layer_Renderer,
    layers: list[np.ndarray],
    k: float,
    zf: float,
    device: torch.device,
) -> list[tuple[torch.Tensor, torch.Tensor, torch.Tensor]]:
    """Each layer scattered on its own by Dr.Bokeh's kernel, as its ``inference`` does before
    it composites: the scattered color, its weight and the layer's occupancy."""
    x = torch.cat(
        [torch.tensor(layer.transpose(2, 0, 1))[None] for layer in layers], dim=1
    )
    x = x.to(device).float()
    x[:, 4::5] -= zf
    lens_effect = (torch.ones(1, 1) * k).to(device).float()
    scattered = []
    for i in range(len(layers)):
        out = renderer.renderer.forward(x[:, 5 * i : 5 * (i + 1)], lens_effect)
        scattered.append((out[:, :3], out[:, 3:4], out[:, 4:5]))
    return scattered


def render_sequence(seq: Path, device: torch.device, composite: str = "linear") -> None:
    strength = float(focus_record(seq)["strength"])
    out = seq / STREAMS[composite]
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
            if composite == "gamma":
                scattered = scatter_layers(renderers[lens], gamma, k, zf, device)
                blur = composite_near_to_far(scattered, 1.0 / GAMMA)
                save_rgb(out, name, blur[0].cpu().numpy().transpose(1, 2, 0))
                continue
            blur = renderers[lens].inference(gamma, k, zf)
        save_rgb(out, name, np.clip(blur, 0.0, 1.0) ** (1.0 / GAMMA))
    write_settings(out, "Dr.Bokeh", seq, gamma=GAMMA, composite=composite)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--seqs", default=None, help="comma-separated sequence ids")
    parser.add_argument(
        "--composite",
        choices=sorted(STREAMS),
        default="linear",
        help="the space the blurred layers are composited in (default: linear, "
        "as Dr.Bokeh's)",
    )
    args = parser.parse_args(argv)
    names = args.seqs.split(",") if args.seqs else None
    device = torch.device("cuda:0")
    for seq in renderable_sequences(args.data_root, names):
        render_sequence(seq, device, args.composite)
        print(f"  {seq.name}: {STREAMS[args.composite]} written", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
