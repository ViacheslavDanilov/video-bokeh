---
type: reference
status: active
tags: [reference, loader, training, pytorch]
related: [dataset-layout, cli]
---

# Sequence stream — the on-the-fly loader

`video_bokeh.loader.SequenceStream` generates a new sequence from a library for every item a
training loop asks for. Nothing is written to disk. It is the same Stage B that
`video_bokeh.scenes.generate` runs, so a model trained on the stream sees the same scenes as
one trained on a written dataset.

## Install

The stream needs torch and nothing else beyond the base install. From the repository root:

```bash
uv sync --no-dev --extra loader
```

## Use

```python
from pathlib import Path
from torch.utils.data import DataLoader
from video_bokeh.loader import SequenceStream

stream = SequenceStream(
    Path("data/library_dev"),
    n_frames=24,
    size=512,
    n_objects_min=1,
    n_objects_max=5,
    seed=0,
)
batches = DataLoader(stream, batch_size=4, num_workers=4)
batch = next(iter(batches))
```

The stream never ends. Stop after as many batches as a run needs.

`n_objects_min` must be at least 1 and no more than `n_objects_max`; anything else is refused
when the stream is created.

## What an item holds

All tensors are float32 in `[0, 1]`, frames first. `T` is `n_frames`, `H` and `W` are `size`.

| key | shape | meaning |
|---|---|---|
| `rgb` | (T, 3, H, W) | the all-in-focus frames |
| `disparity` | (T, 1, H, W) | disparity, near larger, as in the `disparity` stream |
| `alpha` | (T, 1, H, W) | the union of every object's matte |
| `object_alphas` | (T, `n_objects_max`, H, W) | one matte per object, in the alpha stream's page order, zero past `n_objects` |
| `n_objects` | int | objects actually placed |
| `seed` | int | the seed this sequence came from |

`object_alphas` is padded so every item has the same shape, which is what lets the default
collate batch sequences with different object counts. Use `n_objects` to ignore the padding.

## Seeds and workers

Worker `w` of `W` takes seeds `seed + w`, `seed + w + W`, `seed + w + 2W`, and so on.

- **Workers never repeat each other.** Each seed goes to exactly one worker.
- **A run is reproducible.** The same `seed` and the same `num_workers` give the same stream.
- **One worker matches the written dataset.** With `num_workers` of 0 or 1, the stream yields
  the scenes of seeds `seed`, `seed + 1`, ... — the ones `video_bokeh.scenes.generate --seed`
  writes. Only the pixels differ: the files on disk are quantized to 8-bit RGB, 8-bit mattes
  and 16-bit disparity, and the stream is not.
- **Nearby seeds give almost the same stream.** Across its workers, one stream uses every
  seed from `seed` upward, so `seed=1` yields what `seed=0` yields, one item later. Two
  streams share no sequence only when their seeds are further apart than the number of
  seeds either one uses. Space them far apart, for example `seed=rank * 10**9`.
- **A written dataset holds seeds too.** `--seed s --count n` writes seeds `s` to
  `s + n - 1`. Keep a training stream's seeds clear of a dataset kept for validation.
- **Every new iterator starts again at `seed`.** A loop that re-creates its iterator each
  epoch sees the same sequences each epoch. Keep one iterator for the whole run, or move
  `seed` far from its last value before each epoch. With `persistent_workers=True`, moving it
  does nothing: each worker keeps the copy of the stream it started with, so build a new
  `DataLoader` instead.

A seed whose objects cannot be placed without colliding is skipped, as the writer skips it.
With `seed` of 0 and one worker, the first item is therefore not always seed 0. After 100
skipped seeds in a row the stream stops with an error, because asking for fewer objects is
the only way out.

## Limits

- **No bokeh.** Rendering bokeh per item is too heavy for a data loader. Bokeh is Stage C's
  job, run over written sequences.
- **CPU only.** Each worker generates on the CPU. Use `num_workers` to scale.
- **No split across distributed ranks.** Every process with the same `seed` yields the same
  stream, and nearby seeds overlap, as above. Give each rank a seed far from the others', for
  example `seed=rank * 10**9`.
- **Assets are read from disk for every item.** That is the first thing to cache if the
  stream cannot keep a training loop fed.
