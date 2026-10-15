#!/usr/bin/env python3
"""Render sequences' bokeh with MPIB's ray tracer, from our own layers.

Runs inside ``comparison/envs/render`` (see ``comparison/README.md``). It skips every sequence
under ``--data-root`` that was not written with ``--layers`` or holds no ``bokeh/focus.json``.
For each of the others, it renders every frame from the same layers, focus disparity and
strength as our layered renderer did, and writes

    <sequence>/bokeh_mpib_rt/<frame>.png   RGB uint8, the sequence's size
    <sequence>/bokeh_mpib_rt/run.json      the settings, so the two renders compare like for like

MPIB's ray tracer (``bokeh_generator.py`` of https://github.com/JuewenPeng/MPIB, Sec. 3.4 of
its paper) is the generator that made that paper's training data. It traces rays through a thin
lens and the layers, nearest first. Each layer carries an alpha mask and ONE plane, not a
disparity map: the plane ``Z = C + A X + B Y`` in depth ``Z = 1 / disparity``. So the object's
relief inside a layer is lost, which our renderer keeps, and this render is a reference for
edges and occlusion, not for the blur inside an object. The plane of each layer is the least
squares fit of its disparity, under its alpha, by ``d = p0 + p1 x + p2 y``, with ``C = 1/p0``,
``A = -p1 C`` and ``B = -p2 C``.

The lens radius ``K`` is in pixels per unit of disparity from the focus, which is our strength
scaled to the frame's width. The focus is given as a depth, ``1 / zf``. Colors go through the
power of 2.2 around the render, as for our renderer.

Usage:
    comparison/envs/render/bin/python comparison/run_mpib_rt.py --data-root data/synth_dev
"""

from __future__ import annotations

import argparse
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

sys.path.insert(0, str(REPO / "comparison" / "third_party" / "mpib"))

from bokeh_generator import ModuleRenderRT  # noqa: E402
from planes import MIN_DISPARITY, fit_plane  # noqa: E402

#: Aperture samples on a side of the lens's bounding square, about 2000 inside the circle.
SAMPLES_PER_SIDE = 51


def layers_near_to_far(frame: LayeredFrame, device: torch.device):
    """``(images, alphas, coffs)`` for the ray tracer: ``(1, N, 3, H, W)``, ``(1, N, 1, H, W)``
    and ``(1, N, 3)``, the nearest layer first and the opaque background last."""
    colors, alphas, planes = [], [], []
    for page in reversed(list(frame.paint_order)):
        alpha = frame.object_alphas[page]
        colors.append(frame.object_rgbs[page])
        alphas.append(alpha[None])
        planes.append(fit_plane(frame.object_disparities[page], alpha))
    h, w = frame.background.shape[1:]
    colors.append(frame.background)
    alphas.append(np.ones((1, h, w), dtype=np.float32))
    planes.append(fit_plane(frame.background_disparity[0], np.ones((h, w))))
    images = torch.from_numpy(np.stack(colors) ** GAMMA).float()[None].to(device)
    masks = torch.from_numpy(np.stack(alphas)).float()[None].to(device)
    coffs = torch.tensor(planes, dtype=torch.float32)[None].to(device)
    return images, masks, coffs


def render_sequence(seq: Path, device: torch.device, samples: int) -> None:
    strength = float(focus_record(seq)["strength"])
    out = seq / "bokeh_mpib_rt"
    renderer = ModuleRenderRT().to(device)
    for name, zf, frame in frames_with_focus(seq):
        images, alphas, coffs = layers_near_to_far(frame, device)
        k = strength * images.shape[-1] / REFERENCE_WIDTH
        with torch.no_grad():
            blur = renderer(
                images, alphas, coffs, k, 1.0 / max(zf, MIN_DISPARITY), samples
            )
        # A pixel whose every ray missed the frame is NaN; the opaque background makes it rare.
        blur = torch.nan_to_num(blur)
        rgb = blur[0].clamp(0, 1).permute(1, 2, 0).cpu().numpy() ** (1.0 / GAMMA)
        save_rgb(out, name, rgb)
    write_settings(out, "MPIB ray tracer", seq, gamma=GAMMA, samples_per_side=samples)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--seqs", default=None, help="comma-separated sequence ids")
    parser.add_argument("--samples", type=int, default=SAMPLES_PER_SIDE)
    args = parser.parse_args(argv)
    names = args.seqs.split(",") if args.seqs else None
    device = torch.device("cuda:0")
    for seq in renderable_sequences(args.data_root, names):
        render_sequence(seq, device, args.samples)
        print(f"  {seq.name}: bokeh_mpib_rt written", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
