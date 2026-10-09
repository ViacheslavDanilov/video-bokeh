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
when the stream is created. So is a `library_root` with no foregrounds or no backgrounds, which
would otherwise fail inside a DataLoader worker once iteration starts. `cfg`, a `SampleConfig`,
changes the pose and motion ranges the way it does for the dataset writer; leave it out for the
writer's defaults.

## What an item holds

An item holds the streams `streams` names, plus `n_objects` and `seed`. Without `streams` it
holds `rgb`, `disparity`, `alpha` and `object_alphas`, as it always did.

All tensors are float32 in `[0, 1]`, frames first, except `paint_order`. `T` is `n_frames`,
`H` and `W` are `size`, and `N` is `n_objects_max`.

| stream | key | shape | meaning |
|---|---|---|---|
| `rgb` | `rgb` | (T, 3, H, W) | the all-in-focus frames |
| `disparity` | `disparity` | (T, 1, H, W) | disparity, near larger, as in the `disparity` stream |
| `alpha` | `alpha` | (T, 1, H, W) | the union of every object's matte |
| `object_alphas` | `object_alphas` | (T, N, H, W) | one matte per object, in the alpha stream's page order, zero past `n_objects` |
| `layers` | `background` | (T, 3, H, W) | the whole background, nothing in front of it |
| | `background_disparity` | (T, 1, H, W) | its disparity |
| | `object_rgbs` | (T, N, 3, H, W) | each whole object's colour, zero outside its alpha mask |
| | `object_disparities` | (T, N, H, W) | each whole object's disparity, zero outside its alpha mask |
| | `paint_order` | (T, N), int64 | the objects far to near in each frame, then the padding |
| always | `n_objects` | int | objects actually placed |
| always | `seed` | int | the seed this sequence came from |

`object_alphas` and the object layers are padded so every item has the same shape, which is
what lets the default collate batch sequences with different object counts. Use `n_objects`
to ignore the padding.

### Choosing streams

```python
stream = SequenceStream(Path("data/library_dev"), n_frames=24, size=512,
                        streams=("rgb", "disparity"))
```

- **Ask only for what the loop uses.** Each stream is stacked in the worker and copied to the
  training process, so a stream the loop discards still costs time.
- **An unknown name, or none at all, is refused** when the stream is created.
- **`layers` is what a layer-wise bokeh renderer needs**, together with `object_alphas`: object
  `k`'s alpha is `object_alphas[:, k]`. Compositing the object layers over the background in
  `paint_order` gives back `rgb`. The layers hold eight times as many floats as `rgb` at
  five objects, so ask for them only when the loop uses them.

### What each choice costs

Measured on the lab machine (24 cores) on 2026-10-10: 512 pixels, 24 frames, 1 to 5
objects, batches of 4, from the 30-asset development library.

| streams | items/s, no workers | items/s, 8 workers | MiB per item |
|---|---|---|---|
| `rgb`, `disparity` | 0.56 | 2.91 | 96 |
| the default four | 0.56 | 2.82 | 240 |
| the default four and `layers` | 0.46 | 2.17 | 816 |

- **Generating the scene is the cost, not stacking the streams.** Dropping to two streams
  saves 3 %; adding the layers costs 23 %.
- **Memory is what the layers really cost.** A `DataLoader` keeps `prefetch_factor` batches per
  worker in shared memory, 2 by default, so 8 workers with layers can hold 16 batches of 4,
  about 51 GiB. Fewer workers, a smaller `prefetch_factor` or fewer frames bring it down. In a
  container, `/dev/shm` has to be that large too.

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

- **No bokeh yet.** The `layers` stream carries what a layer-wise renderer needs; the renderer
  itself is not in the stream yet. Bokeh is Stage C's job, run over written sequences.
- **CPU only.** Each worker generates on the CPU. Use `num_workers` to scale.
- **No split across distributed ranks.** Every process with the same `seed` yields the same
  stream, and nearby seeds overlap, as above. Give each rank a seed far from the others', for
  example `seed=rank * 10**9`.
- **Assets are read from disk for every item.** That is the first thing to cache if the
  stream cannot keep a training loop fed.
