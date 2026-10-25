---
type: how-to
status: active
tags: [how-to, loader, training, bokeh]
related: [loader, layered-bokeh]
---

# Train a network on the sequence stream

The sequence stream generates a new sequence for every item a training loop asks for, with its
bokeh if asked, and writes nothing to disk. This page downloads the published library and runs
a small training loop on it end to end. [loader](../reference/loader.md) describes every
stream and option.

The project works in two stages. Stage A builds a library once: cut-out objects and background
photos, each with a disparity map. Stage B composes sequences from the library on the fly,
moving the objects over a background, and the sequence stream runs it inside a PyTorch
`DataLoader`.

## 1. Install

You need Python 3.13 and [uv](https://docs.astral.sh/uv/). Clone the code and install the
`loader` extra, which brings torch and the Hugging Face client:

```bash
git clone https://github.com/ViacheslavDanilov/video-bokeh
cd video-bokeh/backend
uv sync --no-dev --extra loader
```

## 2. Download the library

**The library is on Hugging Face as
[vdanilov/video-bokeh](https://huggingface.co/datasets/vdanilov/video-bokeh).** It holds 8,586
cut-out objects and 20,000 background photos, each with a disparity map, in 115 GB of tar
shards. Every `depth.png` in it holds disparity, larger values nearer. `fetch` downloads the
shards one at a time and unpacks each into the folder layout Stage B reads, so the disk needs
the library plus room for one shard of 2 GB. From `backend/`:

```bash
uv run python -m video_bokeh.library.hub fetch --repo vdanilov/video-bokeh \
  --output data/library/da2-large
```

On the lab machine on 2026-10-25 it took 20 minutes, and the files it wrote matched the source
library byte for byte. Run it again after an interruption, and it downloads only the shards it
has not unpacked yet. To build a library of your own instead, follow Stage A in
[generate-a-dataset](generate-a-dataset.md).

## 3. Run the example

`video_bokeh.loader.example` trains a small network to turn all-in-focus frames and their
disparity into bokeh, on sequences of 8 frames at 256 pixels, for 20 steps. From `backend/`:

```bash
uv run python -m video_bokeh.loader.example --library-root data/library/da2-large
```

Without `--library-root` it reads `data/library_dev/da2-large`, the small development library
that `make libraries` builds from the pools a clone carries.

It prints one line per step. On the lab machine on 2026-10-25, with the network on an RTX 5090
and the library from step 2, the 20 steps took 21 s and the loss fell from 0.4876 to 0.1646. On
an Apple M3 Pro on 2026-10-10 the 20 steps took 41 s on the CPU. The network's weights start
unseeded, so no two runs print the same.

Read its source as a template for your own loop:

- **It asks the stream for `rgb`, `disparity` and `bokeh`**, and the `DataLoader`'s four
  workers render the bokeh on the CPU. The batches arrive finished, and the GPU stays with the
  network.
- **It turns a batch of sequences into a batch of frames** with `flatten(0, 1)`, because the
  network is per frame.
- **Its loop runs inside `main()` behind `if __name__ == "__main__"`**, which
  [loader](../reference/loader.md) says a script needs.
- **It leaves the stream's `seed` at 0.** The seed picks the sequences. Give every rank of a
  distributed run its own, far apart, as [loader](../reference/loader.md) explains.

A loop of your own starts from the same few lines. Each batch is a dict of tensors, frames
first, with the images as float32 in [0, 1]. [loader](../reference/loader.md) lists every stream
an item can carry, such as the mattes, the layers, the focus, optical flow and occlusion:

```python
from pathlib import Path

from torch.utils.data import DataLoader

from video_bokeh.loader import SequenceStream


def main() -> None:
    stream = SequenceStream(
        Path("data/library/da2-large"),
        n_frames=8,
        size=256,
        streams=("rgb", "disparity", "bokeh", "flow"),
    )
    for batch in DataLoader(stream, batch_size=4, num_workers=4):
        rgb, disparity = batch["rgb"], batch["disparity"]  # (B, T, 3 or 1, H, W)
        bokeh, flow = batch["bokeh"], batch["flow"]  # flow: (B, T - 1, 2, H, W)
        ...  # your training step


if __name__ == "__main__":
    main()
```

## 4. When the workers cannot keep up

**Bokeh rendered in the workers is the simple path, and the slow one.** On the lab machine it
tops out near 0.9 items per second at 512 pixels and 24 frames, however many workers render it.
[loader](../reference/loader.md) has the measurements.

At that rate a batch of 4 takes about 4.5 s to arrive. A training step shorter than that waits
for the loader. Then ask the workers for the layers instead of the bokeh, and render each batch
on the GPU with `batch_bokeh`. [loader](../reference/loader.md) has the recipe and what it costs.

## 5. Read the library without the code

**The shards follow WebDataset's layout,** so the `datasets` library streams them from the Hub
with no download and no code of ours, one sample per item. Use it to inspect the data. Training
needs the sequences, which only the code generates.

It needs `datasets` and Pillow, nothing else. With uv, outside the project:

```bash
uv run --no-project --with datasets --with pillow python - <<'EOF'
from datasets import load_dataset

foregrounds = load_dataset("vdanilov/video-bokeh", "foregrounds", split="train", streaming=True)
item = next(iter(foregrounds))
print(sorted(item), item["depth.png"].mode)
EOF
```

On an Apple M3 Pro on 2026-10-25 it printed the first item's keys and `I;16`, the 16-bit
disparity, in 25 s on the first run, installing both libraries included, and in 5 s after.

An item holds `rgb.png`, `alpha.png` and `depth.png` as PIL images, the depth one 16-bit,
`depth_preview.jpg`, a colored view of the disparity, `json`, the item's metadata, and
`__key__`, its id. The `backgrounds` subset holds `rgb.png`, `depth.png` and
`depth_preview.jpg`.
