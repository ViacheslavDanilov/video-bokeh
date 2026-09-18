---
type: how-to
status: active
tags: [how-to, dataset, pipeline, runbook]
related: [dataset-layout, cli, pipeline-explainer]
---

# Generate a dataset

Two stages. Stage A estimates depth once per asset and is slow; Stage B composites sequences
from those assets and is fast. Run Stage A once, then Stage B as often as you like.

Every command here runs from `backend/` and has been executed as written. Output lands in
`backend/data/`, which is gitignored.

For what the commands write, see [[dataset-layout]]. For every flag, see [[cli]]. For why the
pipeline is shaped this way, see [[pipeline-explainer]].

---

## Before you start

1. Foregrounds in `data/magick_dev` — see [[magick]].
2. Backgrounds in `data/bg-20k_dev` — see [[datasets]].
3. Dependencies: `uv sync --extra library` from the repo root.

If `data/library_dev/` already holds `foregrounds/` and `backgrounds/`, Stage A is done and
you can skip to Stage B. The current `library_dev` has 12 foregrounds and 20 backgrounds,
which is enough for every recipe below.

---

## 1. Stage A — build the library

```bash
uv run python -m video_bokeh.library.build \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output data/library_dev --size 1024 --model da2-large
```

**`--size` must match Stage B.** Stage B warps the library's images into the frame, so they
have to start at the frame resolution. A mismatch corrupts the output rather than failing.

**The CLIP filter drops assets.** Stage A keeps only foregrounds whose predicted subject and
style clear `--subject-thr`, so 20 inputs may yield about 12 in the library. Pass
`--subjects ""` to turn it off.

A fast check with no large download — 3 foregrounds, 2 backgrounds, the small model, **6.7 s**
on an M-series Mac using `mps`:

```bash
uv run python -m video_bokeh.library.build \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output /tmp/lib_smoke --size 256 --model da2-small \
  --limit-fg 3 --limit-bg 2
```

---

## 2. Stage B — generate sequences

```bash
uv run python -m video_bokeh.scenes.generate \
  --library-root data/library_dev --output data/demo \
  --count 4 --frames 80 --size 512 --seed 0
```

**Objects move freely through depth**, and their on-screen size and their distance move
together. Every sampled trajectory set is checked against collisions, and one that cannot be
made collision-free is resampled rather than written.

Measured on `library_dev`, 4 sequences of 80 frames at size 512: **18 s** on an Apple M3 Pro.
Most of that is the collision validator, which warps every mask on every frame and pays that
cost again for each rejected attempt.

**Sequence names follow the seed.** Sequence `i` always comes from `seed + i`, so a sequence
the validator rejects leaves a gap in the numbering instead of shifting every later sequence
onto a different seed.

### More than three objects

There is no format ceiling: the alpha stream is a multi-page TIFF and takes as many masks as
it is given. `--n-objects-max` defaults to 5.

```bash
uv run python -m video_bokeh.scenes.generate \
  --library-root data/library_dev --output data/demo5 \
  --count 3 --frames 8 --size 512 --n-objects-min 5 --n-objects-max 5
```

What binds now is the depth axis, not the image format. Objects get disjoint slots above the
background, so each extra object narrows every slot and makes collisions harder to avoid.
Five places every scene; six starts losing them. The measured sweep is in
[[demo-unrestricted-trajectories]], and [[dataset-layout]] says what to raise if you need
more.

---

## 3. Read the manifest

```bash
column -s, -t < data/demo/manifest.csv
```

```
seq_id  seed  n_frames  size  n_objects  n_rejections  n_range_fallbacks
0001    0     80        512   1          0             0
0002    1     80        512   3          0             0
0003    2     80        512   4          0             0
```

`n_rejections` counts trajectory sets the collision validator threw away; it climbs with
object count. `n_range_fallbacks` counts objects that could not find an end pose within the
retry budget and held their start scale instead — expect `0`, and treat anything else as a
sign the depth axis is unusually tight. Column meanings in full: [[dataset-layout]].

---

## 4. Look at the result

`vpv` opens synchronized panes. Run it from inside the dataset's `sequences/` directory:

```bash
cd data/demo/sequences
vpv "*/all_in_focus/*.png" "*/disparity/*.png"
```

What to check:

- **Disparity tracks size.** An object that grows on screen must get brighter in the
  disparity pane. Growing while darkening means the depth-scale law inverted, which is the
  one regression this pipeline exists to prevent.
- **Each object keeps its page.** Page `k` is object `k` for the whole clip. A mask that
  jumps pages mid-clip is a bug. `vpv` shows only the first page of a TIFF, so check the
  masks with `read_alpha_tiff` rather than by eye.
- **Overlap is unambiguous.** Two objects may overlap on screen but never at the same depth,
  so one is always clearly in front.

A fuller set of checks on the trajectory model is in [[demo-unrestricted-trajectories]].

---

## 5. Hand it to the renderer

```bash
uv run python -m video_bokeh.bridge.any_to_bokeh --data-root data/demo
```

See [[run-any-to-bokeh-inference]].

---

## Clean up

```bash
rm -rf data/demo data/demo5
```
