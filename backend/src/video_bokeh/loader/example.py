"""Train a small network to predict bokeh from all-in-focus frames and their disparity.

An example of a training loop on the sequence stream, end to end: every item is a new
sequence with its bokeh, rendered in the DataLoader's workers on the CPU. Run from
``backend/``:

    uv run python -m video_bokeh.loader.example
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader

from video_bokeh.loader import SequenceStream


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, default=Path("data/library_dev"))
    parser.add_argument("--steps", type=int, default=20)
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    stream = SequenceStream(
        args.library_root,
        n_frames=8,
        size=256,
        streams=("rgb", "disparity", "bokeh"),
    )
    # In: the frame's 3 colour channels and its disparity. Out: the bokeh's 3.
    net = nn.Sequential(
        nn.Conv2d(4, 32, 3, padding=1),
        nn.ReLU(),
        nn.Conv2d(32, 3, 3, padding=1),
    ).to(device)
    optimizer = torch.optim.Adam(net.parameters(), lr=1e-3)
    batches = DataLoader(stream, batch_size=4, num_workers=4)
    for step, batch in zip(range(args.steps), batches, strict=False):
        # Frames of every sequence in the batch become one batch of images.
        x = torch.cat([batch["rgb"], batch["disparity"]], dim=2).flatten(0, 1)
        y = batch["bokeh"].flatten(0, 1)
        loss = nn.functional.l1_loss(net(x.to(device)), y.to(device))
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        print(f"step {step:2d}  loss {loss.item():.4f}")


# The guard is not optional: under spawn or forkserver, each DataLoader worker imports
# this module again.
if __name__ == "__main__":
    main()
