---
type: how-to
status: active
tags: [how-to, loader, training, bokeh]
related: [loader, layered-bokeh]
---

# Train a network on the sequence stream

The sequence stream generates a new training sequence for every item a loop asks for and
writes nothing to disk. This page downloads the published library and trains a small network
on it. [loader](../reference/loader.md) describes every stream and option.

The project works in two stages. Stage A built the library once: cut-out objects and
background photos, each with a disparity map. Stage B composes sequences from it on the fly,
moving the objects over a background, and the sequence stream runs Stage B inside a PyTorch
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
cut-out objects and 20,000 background photos in 115 GB of tar shards. Every `depth.png` holds
disparity, larger values nearer. `fetch` downloads the shards one at a time and unpacks each
into the folder layout Stage B reads, so the disk needs the library plus room for one 2 GB
shard:

```bash
uv run python -m video_bokeh.library.hub fetch --repo vdanilov/video-bokeh \
  --output data/library/da2-large
```

It takes about 20 minutes at 100 MB/s. If it stops, run it again: it downloads only
the shards it has not unpacked yet.

## 3. Run the example

`video_bokeh.loader.example` trains a small network to turn all-in-focus frames and their
disparity into bokeh, rendered at strength `k = 16`, on sequences of 8 frames at 256 pixels,
for 20 steps:

```bash
uv run python -m video_bokeh.loader.example --library-root data/library/da2-large
```

It prints the loss at every step. On a 24-core machine with an RTX 5090 the 20 steps take about
20 s, and the loss falls from about 0.5 to under 0.2. Read its source as a template for your
own loop:

- **It asks the stream for `rgb`, `disparity` and `bokeh`**, and the `DataLoader`'s four
  workers render the bokeh on the CPU. The batches arrive finished, and the GPU stays with the
  network.
- **It turns a batch of sequences into a batch of frames** with `flatten(0, 1)`, because the
  network is per frame.
- **Its loop runs inside `main()` behind `if __name__ == "__main__"`**, which
  [loader](../reference/loader.md) says a script needs.
- **It leaves the stream's `seed` at 0.** The seed picks the sequences. Give every rank of a
  distributed run its own, far apart, as [loader](../reference/loader.md) explains.

## 4. Write your own loop

Each batch is a dict of tensors, frames first, with the images as float32 in [0, 1].
[loader](../reference/loader.md) lists every stream an item can carry, such as the mattes, the
layers, the focus, optical flow and occlusion:

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
        bokeh_strength=16.0,
    )
    for batch in DataLoader(stream, batch_size=4, num_workers=4):
        rgb, disparity = batch["rgb"], batch["disparity"]  # (B, T, 3 or 1, H, W)
        bokeh, flow = batch["bokeh"], batch["flow"]  # flow: (B, T - 1, 2, H, W)
        ...  # your training step


if __name__ == "__main__":
    main()
```

**The arguments set what each item holds.** `n_frames` is the length of a sequence and `size`
the side of its frames in pixels. `streams` names what an item carries. `bokeh_strength` is the
bokeh's strength `k`: the blur radius in pixels, at a 1024-pixel width, of a point one unit of
disparity from the focus. It is 16 unless set, and one value holds for the whole stream. The
focus follows one object of each sequence, drawn at random with odds by the area it alone
covers; `focus_disparity=` pins one disparity for every frame instead.

## 5. When the workers cannot keep up

**Bokeh rendered in the workers is the simple path, and the slow one.** On a 24-core machine it
tops out near 0.9 items per second at 512 pixels and 24 frames, however many workers render it,
so a batch of 4 takes about 4.5 s to arrive. A training step shorter than that waits for the
loader. Then ask the workers for the layers instead of the bokeh, and render each batch on the
GPU with `batch_bokeh`, where `k` can change from batch to batch.
[loader](../reference/loader.md) has the recipe and what it costs.

## 6. Read the library without the code

**The shards follow WebDataset's layout,** so the `datasets` library streams them from the Hub
with no download and no code of ours, one sample per item. Use it to inspect the data.
Training needs the sequences, which only the code generates. It needs `datasets` and Pillow,
nothing else:

```bash
uv run --no-project --with datasets --with pillow python - <<'EOF'
from datasets import load_dataset

foregrounds = load_dataset("vdanilov/video-bokeh", "foregrounds", split="train", streaming=True)
item = next(iter(foregrounds))
print(sorted(item), item["depth.png"].mode)
EOF
```

An item holds `rgb.png`, `alpha.png` and `depth.png` as PIL images, the depth one 16-bit,
`depth_preview.jpg`, a colored view of the disparity, `json`, the item's metadata, and
`__key__`, its id. The `backgrounds` subset holds `rgb.png`, `depth.png` and
`depth_preview.jpg`.
