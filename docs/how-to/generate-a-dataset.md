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

For what the commands write, see [dataset-layout](../reference/dataset-layout.md). For every
flag, see [cli](../reference/cli.md). For why the pipeline is shaped this way, see
[pipeline-explainer](../explanation/pipeline-explainer.md).

---

## Before you start

1. Foregrounds in `data/magick_dev` — see [magick](../explanation/magick.md).
2. Backgrounds in `data/bg-20k_dev` — see [datasets](../explanation/datasets.md).
3. Dependencies: `uv sync --extra library` from the repo root.
4. On a new machine, `uv run --extra library python -m video_bokeh.library.check` says whether
   each depth estimator can run there, before a build finds out. See [cli](../reference/cli.md).

If `data/library/da2-large/` already holds `foregrounds/` and `backgrounds/`, as `make
libraries` leaves it, Stage A is done and you can skip to Stage B. Built with the default class
filter from the pools as of 2026-10-01, it holds 17 foregrounds and 30 backgrounds, and 30 and
30 with the filter off. Either is enough for every recipe below.

### How the dev pools were grown to 30 and 30

On 2026-10-01, from `backend/`, keeping the 20 of each that were there:

1. `uv run --extra acquire python -m video_bokeh.acquire.magick --metadata data/magick_metadata.csv --output data/magick_dev --count 30 --seed 11`
   downloads ten foregrounds. Seed 11 drew the first twenty, and a larger count keeps them,
   because the sample keeps its order as it grows.
2. `uv run --extra acquire python -m video_bokeh.acquire.classify --data-root data/magick_dev --keep-existing --num-workers 0`
   classifies the ten new ones and keeps the twenty predictions there. The default model,
   ViT-L-14, classified the ten, while the twenty came from PE-Core-bigG-14-448, as
   `data/magick_dev/predictions.json` records. A ViT-L-14 run over those twenty gave five of
   them another top class and would have shrunk the class filter's keep from 12 to 8.
   `--keep-existing` now refuses predictions another model made, so this step would stop
   today; classifying all thirty afresh with one model is how to grow the pool next time.
3. `uv run --extra acquire python -m video_bokeh.acquire.bg20k --output data/bg-20k_dev --count 30 --seed 11`
   fetches ten backgrounds one file at a time from Kaggle, with no archive download. It needs
   `~/.kaggle/kaggle.json`.

The pools grew by 20.8 MiB.

### Full pools

Download all 11,868 hand-picked MAGICK foregrounds and the whole BG-20k archive from
`backend/`:

```bash
uv run --frozen --no-sync python -m video_bokeh.acquire.magick \
  --metadata data/magick/metadata.csv --output data/magick --count 11868
uv run --frozen --no-sync python -m video_bokeh.acquire.bg20k --output data/bg-20k
```

MAGICK writes `data/magick/images/<first-two-characters>/<page_id>.png`, skips existing
images, and preserves the order of existing metadata rows. It retries HTTP 429 and 5xx
responses up to seven attempts, waiting for `Retry-After` when provided or backing off
from 5 to 60 seconds. Failed images can be fetched by rerunning the command.

BG-20k writes `data/bg-20k/images/{train,testval}/<file>` and a `metadata.csv` with
`filename,split` columns, matching the dev pool. It reuses an archive already downloaded
under the output directory and removes the archive copy after building the pool.
Use `data/magick` and `data/bg-20k` as Stage A's source roots.

---

## 1. Stage A — build the library

```bash
uv run python -m video_bokeh.library.build \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output data/library/da2-large --size 1024 --model da2-large
```

**`--size` need not match Stage B.** Stage B maps each asset onto the frame whatever its
size. A library smaller than the frame is only upscaled, and looks softer for it.

**The CLIP filter drops assets.** Stage A keeps only foregrounds whose predicted subject and
style are among `--subjects` and `--styles`, and whose subject score is at least
`--subject-thr`, so the dev pool's 30 foregrounds yield 17 in the library. Pass
`--subjects "" --styles "" --subject-thr 0` to turn it off; any one of them alone leaves the
other two filtering.

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
  --library-root data/library/da2-large --output data/demo \
  --count 4 --frames 80 --size 512 --seed 0
```

**Objects move freely through depth**, and their on-screen size and their distance move
together. Every sampled trajectory set is checked against collisions, and one that cannot be
made collision-free is resampled rather than written.

4 sequences of 80 frames at size 512 took **18 s** on an Apple M3 Pro.
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
  --library-root data/library/da2-large --output data/demo5 \
  --count 3 --frames 8 --size 512 --n-objects-min 5 --n-objects-max 5
```

What binds now is the depth axis, not the image format. Objects get disjoint slots above the
background, so each extra object narrows every slot and makes collisions harder to avoid. Five
places every scene; six starts losing them. The measured sweep is in
[demo-unrestricted-trajectories](demo-unrestricted-trajectories.md), and
[dataset-layout](../reference/dataset-layout.md) says what to raise if you need more.

### Optical flow

`--flow` writes each frame's exact forward optical flow to the next into `flow/`, in the same
pass as the frames:

```bash
uv run python -m video_bokeh.scenes.generate \
  --library-root data/library/da2-large --output data/demo_flow \
  --count 3 --frames 80 --size 512 --seed 0 --flow
```

With the old PNG compression default, level 6, it took 20 s on an Apple M3 Pro on
2026-10-10, against 14 s for the same three sequences without `--flow`. Each sequence's
`flow/` held 79 files, 2.2 to 3.5 MiB in all. The writer now uses level 3. On a 512 px,
seed 3 sequence measured on 2026-10-12, it saved 26.6% of writer time and used 2.67 MiB
instead of 1.71 MiB, with identical decoded pixels.
[dataset-layout](../reference/dataset-layout.md#the-flow-stream--optional) has the format and
the compression measurements. The earlier total generation timings have not been remeasured.

---

## 3. Read the manifest

`manifest.csv` marks a finished run. The writer removes any old manifest when generation
starts and writes the new one last, after `objects.csv` and `run.json`.

```bash
column -s, -t < data/demo/manifest.csv
```

```
seq_id  seed  n_frames  size  n_objects  n_rejections  n_range_fallbacks
0001    0     80        512   1          0             0
0002    1     80        512   3          0             0
0003    2     80        512   4          0             0
```

`n_rejections` counts trajectory sets the collision validator threw away; it climbs with object
count. `n_range_fallbacks` counts objects that could not find an end pose within the retry
budget and held their start scale instead — expect `0`, and treat anything else as a sign the
depth axis is unusually tight. Column meanings in full:
[dataset-layout](../reference/dataset-layout.md).

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

A fuller set of checks on the trajectory model is in
[demo-unrestricted-trajectories](demo-unrestricted-trajectories.md).

---

## 5. Render bokeh

**One run writes the frames and their bokeh**, with the layered renderer that
[layered-bokeh](../explanation/layered-bokeh.md) explains. It runs on any machine with torch
installed.

```bash
uv run python -m video_bokeh.scenes.generate \
  --library-root data/library/da2-large --output data/demo_bokeh \
  --count 2 --frames 24 --size 512 --seed 0 --bokeh
```

It took 7 s on an Apple M3 Pro, on 2026-10-10.

**Stage C renders bokeh over sequences already written**, the layered renderer from the layers
`--layers` wrote:

```bash
uv run python -m video_bokeh.scenes.generate \
  --library-root data/library/da2-large --output data/demo_layers \
  --count 2 --frames 24 --size 512 --seed 0 --layers
uv run --extra render python -m video_bokeh.render.run --data-root data/demo_layers \
  --renderer layered
```

The render took 3 s on an Apple M3 Pro, on 2026-10-10.

**any-to-bokeh needs an NVIDIA card.**
[run-any-to-bokeh-inference](run-any-to-bokeh-inference.md) has the command and says how far it
has been run.

To look at what any-to-bokeh would receive without rendering anything, the bridge converts the
sequences on any machine:

```bash
uv run python -m video_bokeh.bridge.any_to_bokeh --data-root data/demo
```

---

## Clean up

```bash
rm -rf data/demo data/demo5 data/demo_bokeh data/demo_layers
```
