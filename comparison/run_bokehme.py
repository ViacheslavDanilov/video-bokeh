#!/usr/bin/env python3
"""Render sequences' bokeh with BokehMe, from the all-in-focus frame and its disparity.

Runs inside ``comparison/envs/render`` (see ``comparison/README.md``). It skips every sequence
under ``--data-root`` that was not written with ``--layers`` or holds no ``bokeh/focus.json``,
so that the focus and the strength are the ones our renderer recorded. For each of the others,
it renders every frame and writes two streams beside ours:

    <sequence>/bokeh_bokehme/<frame>.png            the hybrid: classical scatter, repaired
                                                    by BokehMe's two networks where they
                                                    judge the scatter wrong
    <sequence>/bokeh_bokehme_classical/<frame>.png  the classical scatter alone

BokehMe (https://github.com/JuewenPeng/BokehMe, CVPR 2022; Apache-2.0) takes one image and one
disparity map and cannot take layers, so it must guess what an object hides. That is why it is
a comparator and not a reference. Its ``pipeline`` function is run as the repository's
``demo.py`` defines it, loaded from that file without its command line; only the inputs differ
from the demo's. Its demo reads the disparity as 8 bits and rescales it to ``[0, 1]`` per
image. Here the disparity keeps its 16 bits and its scale, because the focus disparity our
renderer recorded is on that scale. The blur ``K`` is in pixels per unit of disparity from the
focus, which is our strength scaled to the frame's width. ``gamma`` is 2.2, as for our renderer.

Usage:
    comparison/envs/render/bin/python comparison/run_bokehme.py --data-root data/synth_dev
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch
from common import (
    GAMMA,
    REFERENCE_WIDTH,
    REPO,
    composite_frame,
    focus_record,
    frame_names,
    renderable_sequences,
    save_rgb,
    write_settings,
)

BOKEHME = REPO / "comparison" / "third_party" / "bokehme"
sys.path.insert(0, str(BOKEHME))

#: The demo's own settings: the ratio of the defocus the networks see to the radius, and the
#: range its gamma is normalized over.
DEMO_ARGS = SimpleNamespace(
    defocus_scale=10.0, gamma_min=1.0, gamma_max=5.0, save_intermediate=False
)


def _load_demo_pipeline() -> dict:
    """The ``pipeline`` function and the network classes of BokehMe's ``demo.py``.

    The file is a script: below its function definitions it parses a command line and renders
    its own example. Only what comes before ``device = ...`` is executed.
    """
    source = (BOKEHME / "demo.py").read_text(encoding="utf-8")
    head, found, _ = source.partition("device = torch.device(")
    if not found:
        raise RuntimeError(
            "BokehMe's demo.py is not the version this adapter was written for"
        )
    namespace: dict = {"__name__": "bokehme_demo", "__file__": str(BOKEHME / "demo.py")}
    exec(compile(head, str(BOKEHME / "demo.py"), "exec"), namespace)
    return namespace


def _networks(namespace: dict, device: torch.device):
    """ARNet and IUNet with the demo's default settings and the repository's checkpoints."""
    arnet = namespace["ARNet"](2, 5, 4, 128, 3, False, "distinct_source", False, "elu")
    iunet = namespace["IUNet"](2, 8, 3, 64, 3, False, "distinct_source", False, "elu")
    for net, name in ((arnet, "arnet"), (iunet, "iunet")):
        checkpoint = torch.load(
            BOKEHME / "checkpoints" / f"{name}.pth",
            map_location=device,
            weights_only=False,
        )
        net.load_state_dict(checkpoint["model"])
        net.to(device).eval()
    return arnet, iunet


def render_sequence(
    seq: Path, namespace: dict, models: tuple, device: torch.device
) -> None:
    record = focus_record(seq)
    strength = float(record["strength"])
    arnet, iunet = models
    classical = namespace["ModuleRenderScatter"]().to(device)
    hybrid_dir, classical_dir = seq / "bokeh_bokehme", seq / "bokeh_bokehme_classical"
    for name, zf in zip(frame_names(seq), record["zf"], strict=True):
        rgb, disparity = composite_frame(seq, name)
        k = strength * rgb.shape[1] / REFERENCE_WIDTH
        defocus = k * (disparity - zf) / DEMO_ARGS.defocus_scale
        image = torch.from_numpy(rgb).permute(2, 0, 1)[None].to(device)
        defocus = torch.from_numpy(defocus.astype(np.float32))[None, None].to(device)
        with torch.no_grad():
            pred, scatter, _, _ = namespace["pipeline"](
                classical, arnet, iunet, image, defocus, GAMMA, DEMO_ARGS
            )
        save_rgb(hybrid_dir, name, pred[0].permute(1, 2, 0).cpu().numpy())
        save_rgb(classical_dir, name, scatter[0].permute(1, 2, 0).cpu().numpy())
    write_settings(hybrid_dir, "BokehMe, hybrid", seq, gamma=GAMMA)
    write_settings(classical_dir, "BokehMe, classical scatter", seq, gamma=GAMMA)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--seqs", default=None, help="comma-separated sequence ids")
    args = parser.parse_args(argv)
    names = args.seqs.split(",") if args.seqs else None
    device = torch.device("cuda:0")
    namespace = _load_demo_pipeline()
    models = _networks(namespace, device)
    for seq in renderable_sequences(args.data_root, names):
        render_sequence(seq, namespace, models, device)
        print(
            f"  {seq.name}: bokeh_bokehme and bokeh_bokehme_classical written",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
