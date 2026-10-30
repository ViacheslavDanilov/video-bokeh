---
type: reference
status: active
tags: [reference, loader, training, pytorch]
related: [dataset-layout, cli]
---

# Sequence stream: the on-the-fly loader

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


def main() -> None:
    stream = SequenceStream(
        Path("data/library_dev/da2-large"),
        n_frames=24,
        size=512,
        n_objects_min=1,
        n_objects_max=5,
        seed=0,
    )
    batches = DataLoader(stream, batch_size=4, num_workers=4)
    batch = next(iter(batches))


if __name__ == "__main__":
    main()
```

The stream never ends. Stop after as many batches as a run needs.
[train-on-the-sequence-stream](../how-to/train-on-the-sequence-stream.md) runs a training loop
on it. The `__main__` guard is not optional in a script. Where workers start by spawn or
forkserver, as on macOS, on Windows and on Linux from Python 3.14, a new process imports the
script again: each worker, or the fork server that starts them. Without the guard that import
would start workers of its own.

`n_objects_min` must be at least 1 and no more than `n_objects_max`; anything else is refused
when the stream is created. So is a `library_root` with no foregrounds or no backgrounds, or
with none in the split asked for, which would otherwise fail inside a DataLoader worker once
iteration starts. `cfg`, a `SampleConfig`, changes the pose and motion ranges the way it does
for the dataset writer; leave it out for the writer's defaults.

**`split` picks the assets the scenes are drawn from.** It is `train` by default, the
foregrounds and backgrounds a network may train on. `test` takes the ones the fixed set is made
of, and `all` takes both. A network trained on `test` or `all` has seen the fixed set's assets,
so its scores on the fixed set overstate how well it generalizes.
[dataset-layout](dataset-layout.md#the-train-and-test-splits) says which asset is in which split.

## What an item holds

An item holds the streams `streams` names, plus `n_objects` and `seed`. Without `streams` it
holds `rgb`, `disparity`, `alpha` and `object_alphas`, as it always did.

All tensors are float32 in `[0, 1]`, frames first, except `paint_order`, `flow` and
`flow_back`. `T` is `n_frames`, `H` and `W` are `size`, and `N` is `n_objects_max`.

| stream | key | shape | meaning |
|---|---|---|---|
| `rgb` | `rgb` | (T, 3, H, W) | the all-in-focus frames |
| `disparity` | `disparity` | (T, 1, H, W) | disparity, near larger, as in the `disparity` stream |
| `alpha` | `alpha` | (T, 1, H, W) | the union of every object's matte |
| `object_alphas` | `object_alphas` | (T, N, H, W) | one matte per object, in the alpha stream's page order, zero past `n_objects` |
| `layers` | `background` | (T, 3, H, W) | the whole background, nothing in front of it |
| | `background_disparity` | (T, 1, H, W) | its disparity |
| | `object_rgbs` | (T, N, 3, H, W) | each whole object's color, zero outside its alpha mask |
| | `object_disparities` | (T, N, H, W) | each whole object's disparity, zero outside its alpha mask |
| | `paint_order` | (T, N), int64 | the objects far to near in each frame, then the padding |
| `focus` | `focus_disparity` | (T,) | the in-focus disparity of each frame |
| | `focus_object` | int | the object the focus follows, by page, or -1 when none does |
| `bokeh` | `bokeh` | (T, 3, H, W) | the frames as the layered renderer blurs them |
| | `focus_disparity`, `focus_object` | | the focus it blurred them at, as for `focus` |
| `flow` | `flow` | (T − 1, 2, H, W) | each frame's forward optical flow to the next, `(u, v)` in pixels: the motion of the front-most surface, as `scenes.generate --flow` writes it, unquantized |
| `flow_back` | `flow_back` | (T − 1, 2, H, W) | each frame but the first's backward optical flow to the previous, `(u, v)` in pixels, as `scenes.generate --flow-back` writes it, unquantized |
| `occlusion` | `occlusion` | (T − 1, 1, H, W) | 1 where a frame's front-most surface is not visible in the next frame, as `scenes.generate --occlusion` writes it |
| always | `n_objects` | int | objects actually placed |
| always | `seed` | int | the seed this sequence came from |

`object_alphas` and the object layers are padded so every item has the same shape, which is
what lets the default collate batch sequences with different object counts. Use `n_objects`
to ignore the padding.

### Choosing streams

```python
stream = SequenceStream(Path("data/library_dev/da2-large"), n_frames=24, size=512,
                        streams=("rgb", "disparity"))
```

- **Ask only for what the loop uses.** Each stream is stacked in the worker and copied to the
  training process, so a stream the loop discards still costs time.
- **An unknown name, or none at all, is refused** when the stream is created.
- **`layers` is what a layer-wise bokeh renderer needs**, together with `object_alphas`: object
  `k`'s alpha is `object_alphas[:, k]`. Compositing the object layers over the background in
  `paint_order` gives back `rgb`. The layers hold `4 · (1 + n_objects_max) / 3` times as many
  floats as `rgb`, eight times at the default of five, so ask for them only when the loop uses
  them.
- **`flow` is exact**, computed from the homographies every layer moves by, and off by default.
  It has one field fewer than there are frames, because the last frame has no next. The
  dataset's `flow` stream in [dataset-layout](dataset-layout.md) holds the same flow, in 1/64 px
  steps. `flow_back` is the same field backward, one fewer than the frames because the first
  frame has no previous. `occlusion` marks the pixels whose surface the next frame does not
  show, where the next frame cannot confirm `flow`.

### Bokeh

`bokeh` blurs each item with the layered renderer, the one `render.run` runs as `--renderer layered`
and [layered-bokeh](../explanation/layered-bokeh.md) explains. It is off by default, so a loop
that does not ask for it pays nothing.

```python
stream = SequenceStream(Path("data/library_dev/da2-large"), n_frames=24, size=512,
                        streams=("rgb", "bokeh"), bokeh_strength=16.0)
```

- **`bokeh_strength`** is the renderer's strength, the blur radius in pixels at a 1024-pixel
  width one unit of disparity from the focus, 16 by default. One value for the whole stream.
- **The focus follows the rule `scenes.generate --bokeh` and `render.run` share**: one object, drawn by the area it holds alone, keyed
  on the scene's seed. A seed written as a dataset with `--bokeh`, or rendered again by
  `render.run`, focuses on the same object. `focus_disparity=` pins one disparity for every frame instead.
- **The worker renders it, on the CPU.** The training loop receives finished batches and the
  GPU stays with the network. CUDA never runs in a worker.

**Rendered in the workers, bokeh costs three quarters of the throughput at 512 pixels and
over four fifths at 1024, and more workers do not win it back. Rendered on the GPU, it costs
a quarter to three tenths, nearly all of it for carrying the layers.** Measured on the lab machine, the way the next section measures:

| streams | where the bokeh renders | items/s, 512 px | items/s, 1024 px |
|---|---|---|---|
| the default four | no bokeh | 1.83 | 0.55 |
| the default four and `bokeh` | the workers' CPU | 0.49 | 0.094 |
| `rgb`, `object_alphas`, `layers`, `focus` | not rendered | 1.40 | 0.40 |
| `rgb`, `object_alphas`, `layers`, `focus` | the RTX 5090, with `batch_bokeh` | 1.39 | 0.39 |

`python -m video_bokeh.loader.benchmark --library-root <library> --streams rgb,object_alphas,layers,focus --gpu-bokeh --device cuda`
runs this measurement, with the flags listed in the [CLI reference](cli.md#video_bokehloaderbenchmark-sequence-stream-throughput).

- **The workers cannot keep up.** At 1024 pixels, with bokeh they deliver 0.094 items per
  second at 4 workers and 0.17 at 8, where without it they deliver 0.55 and 0.84. At 16
  workers the bokeh ran the machine's 125 GiB of memory out and a worker was killed.
- **One worker is slower than none.** A `DataLoader` worker runs PyTorch on one thread, while
  the training process renders on every core: with bokeh, one worker delivered 0.028 items per
  second and none 0.074.
- **The GPU route keeps about three quarters**: 76 % at 512 pixels and 71 % at 1024. The
  layers alone cost that much; rendering them on the GPU costs 1 % to 2 % more.
- **The GPU route needs GPU memory**: an item peaked at 2.4 GiB allocated at 512 pixels and
  9.4 GiB at 1024, on top of the network being trained.

So for training, ask the workers for the layers and render each batch on the GPU:

```python
from pathlib import Path
from torch.utils.data import DataLoader
from video_bokeh.loader import SequenceStream, batch_bokeh


def main() -> None:
    stream = SequenceStream(
        Path("data/library_dev/da2-large"),
        n_frames=24,
        size=512,
        streams=("rgb", "object_alphas", "layers", "focus"),
    )
    for batch in DataLoader(stream, batch_size=4, num_workers=8, pin_memory=True):
        batch = {k: v.cuda(non_blocking=True) for k, v in batch.items()}
        bokeh = batch_bokeh(batch, strength=16.0)  # (4, 24, 3, 512, 512)
        ...  # train on batch["rgb"] and bokeh


if __name__ == "__main__":
    main()
```

The RTX 5090 renders a 512-pixel frame in about 3 ms, a 24-frame item in 0.07 s. The layers
cost shared memory too, as the next section says.

### What each choice costs

`python -m video_bokeh.loader.benchmark --library-root <library>` runs this protocol;
use `--streams` to select each row and `--output` to save the numbers and run settings as JSON.

Measured on the lab machine (24 cores, 125 GiB of memory): 512 and 1024 pixels, 24 frames,
1 to 5 objects, batches of 1, 4 workers, from the full library `da2-large` (8,586 foregrounds
and 20,000 backgrounds) and its train split, with `--batch-size 1 --workers 4 --unordered
--min-timed-batches 128`. A `DataLoader` keeps two batches per worker ready, so each run
first drew twice as many batches as there are workers, then timed 32 items per worker. Timed
any sooner or shorter, the run measures that buffer rather than the workers.

| streams | items/s, 512 px | items/s, 1024 px | MiB per item, 512 px |
|---|---|---|---|
| `rgb` | 1.92 | 0.58 | 72 |
| `rgb`, `disparity` | 1.91 | 0.58 | 96 |
| the default four | 1.83 | 0.55 | 240 |
| the default four and `layers` | 1.41 | 0.40 | 816 |

An item at 1024 pixels holds four times the bytes.

- **Generating the scene is most of the cost.** RGB alone is 5 % faster than the default four
  at 512 pixels and 6 % at 1024; adding the layers costs 23 % and 28 %, for carrying them out
  of the workers.
- **Four times the pixels take three to four times as long**: 3.3 times for the default four,
  3.6 times on the GPU route, and 5.2 times with the bokeh in the workers.
- **More workers help until memory runs out.** At 1024 pixels the default four came at 0.20
  items per second in the training process itself, 0.18 with one worker, 0.55 with 4, 0.84
  with 8 and 0.92 with 16.
- **With small batches, let the loader take them out of order.** A `DataLoader` hands batches
  over in worker order, so a slow scene holds back those other workers have finished. At 512
  pixels and 8 workers, batches of 1 came at 2.55 items per second in order and 3.08 with
  `in_order=False`, as fast as batches of 4 in order. The workers render the same seeds; only
  the order they arrive in is no longer fixed.
- **Memory is what the layers really cost.** A `DataLoader` keeps `prefetch_factor` batches per
  worker in shared memory, 2 by default, so 4 workers with layers at 1024 pixels can hold 8
  items of 3.2 GiB, about 26 GiB. Fewer workers, a smaller `prefetch_factor` or fewer frames
  bring it down. In a container, `/dev/shm` has to be that large too.

## Seeds and workers

Worker `w` of `W` takes seeds `seed + w`, `seed + w + W`, `seed + w + 2W`, and so on.

- **Workers never repeat each other.** Each seed goes to exactly one worker.
- **A run is reproducible.** The same `seed` and the same `num_workers` give the same stream,
  in the same order unless the `DataLoader` runs with `in_order=False`.
- **One worker matches the written dataset.** With `num_workers` of 0 or 1, the stream yields
  the scenes of seeds `seed`, `seed + 1`, ...: the ones `video_bokeh.scenes.generate --seed`
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

- **Workers run on the CPU only.** Use `num_workers` to scale, or render the bokeh on the GPU
  as above.
- **No split across distributed ranks.** Every process with the same `seed` yields the same
  stream, and nearby seeds overlap, as above. Give each rank a seed far from the others', for
  example `seed=rank * 10**9`.
- **Assets are read from disk for every item.** The library is listed once, when the stream
  is made, but each item reads its own foregrounds and background. On a network file system
  that is the first thing to cache, or copy the library to a local disk.
