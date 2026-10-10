---
type: how-to
status: active
tags: [how-to, loader, training, bokeh]
related: [loader, layered-bokeh]
---

# Train a network on the sequence stream

The sequence stream generates a new sequence for every item a training loop asks for, with its
bokeh if asked, and writes nothing to disk. This page runs a small training loop on it end to
end. [[loader]] describes every stream and option.

## 1. Install

The stream needs torch. Install the `loader` extra as [[loader]] says.

It also needs a library. The example reads `data/library_dev`, which `backend/README.md`
builds in about 11 s from the development pools a clone carries.

## 2. Run the example

`video_bokeh.loader.example` trains a small network to turn all-in-focus frames and their
disparity into bokeh, on sequences of 8 frames at 256 pixels, for 20 steps. From `backend/`:

```bash
uv run python -m video_bokeh.loader.example
```

It prints one line per step. On an Apple M3 Pro on 2026-10-10 the 20 steps took 41 s on the
CPU, twice. The loss fell from 0.5472 to 0.1360 in one run and from 0.4434 to 0.0634 in the
other. The network's weights start unseeded, so no two runs print the same. On the lab
machine, from a library built with `da2-large` and with the network on the RTX 5090, the 20
steps took 21 s. `--library-root` points it at another library.

Read its source as a template for your own loop:

- **It asks the stream for `rgb`, `disparity` and `bokeh`**, and the `DataLoader`'s four
  workers render the bokeh on the CPU. The batches arrive finished, and the GPU stays with the
  network.
- **It turns a batch of sequences into a batch of frames** with `flatten(0, 1)`, because the
  network is per frame.
- **Its loop runs inside `main()` behind `if __name__ == "__main__"`.** Where workers start by
  spawning, as on macOS and Windows, each imports the module again. Without the guard it would
  start a loader of its own.
- **It leaves the stream's `seed` at 0.** The seed picks the sequences. Give every rank of a
  distributed run its own, far apart, as [[loader]] explains.

## 3. When the workers cannot keep up

**Bokeh rendered in the workers is the simple path, and the slow one.** On the lab machine it
tops out near 0.9 items per second at 512 pixels and 24 frames, however many workers render it.
[[loader]] has the measurements.

At that rate a batch of 4 takes about 4.5 s to arrive. A training step shorter than that waits
for the loader. Then ask the workers for the layers instead of the bokeh, and render each batch
on the GPU with `batch_bokeh`. [[loader]] has the recipe and what it costs.
