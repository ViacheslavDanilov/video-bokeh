---
type: how-to
status: active
tags: [how-to, dataset, pipeline, runbook]
related: [dataset-layout, cli, pipeline-explainer]
---

# Generate a dataset

Two stages. Stage A estimates depth once per asset and is slow; Stage B composites sequences
from those assets and is fast. Run Stage A once, then Stage B as often as you like.

Every command here runs from `backend/`. Output lands in `backend/data/`, which is
gitignored.

For what the commands write, see [dataset-layout](../reference/dataset-layout.md). For every
flag, see [cli](../reference/cli.md). For why the pipeline is shaped this way, see
[pipeline-explainer](../explanation/pipeline-explainer.md).

---

## Before you start

1. Foregrounds in `data/magick_dev` (see [datasets](../explanation/datasets.md#magick-foregrounds)).
2. Backgrounds in `data/bg-20k_dev` (see [datasets](../explanation/datasets.md#bg-20k-backgrounds)).
3. Dependencies: `uv sync --extra library` from the repo root.
4. On a new machine, `uv run --extra library python -m video_bokeh.library.check` says whether
   each depth estimator can run there, before a build finds out. See [cli](../reference/cli.md).

If `data/library_dev/da2-large/` already holds `foregrounds/` and `backgrounds/`, as `make
libraries` leaves it, Stage A is done and you can skip to Stage B. Built with the default class
filter from the tracked dev pools, it holds 17 foregrounds and 30 backgrounds, and 30 and 30
with the filter off. Either is enough for every recipe below.

### How the dev pools were grown to 30 and 30

From `backend/`, keeping the 20 of each that were there:

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
   no Kaggle account, as [Full pools](#full-pools) says.

The pools grew by 20.8 MiB.

### Full pools

First install the acquisition dependencies from the repo root:

```bash
uv sync --frozen --extra library --extra acquire
```

Then download all 11,868 hand-picked MAGICK foregrounds and the whole BG-20k archive
from `backend/`:

```bash
uv run --frozen --no-sync python -m video_bokeh.acquire.magick \
  --metadata data/magick/metadata.csv --output data/magick --count 11868
uv run --frozen --no-sync python -m video_bokeh.acquire.bg20k --output data/bg-20k
```

`make pools`, from the repository root, runs both commands, BG-20k first, so a Kaggle refusal
shows before MAGICK starts. It skips BG-20k once `data/bg-20k/images/` holds images and no
archive is left under `data/bg-20k/datasets/`, as after a finished run or a download by hand.
A finished run removes its copy of the archive, so running the command again would download it
again. A run stopped while copying keeps its unpacked archive, so a rerun finishes the copy
without downloading again. Images downloaded by hand go in the layout each command writes,
below.

MAGICK writes `data/magick/images/<first-two-characters>/<page_id>.png`, skips existing
images, and preserves the order of existing metadata rows. It retries HTTP 429 and 5xx
responses up to seven attempts, waiting for `Retry-After` when provided or backing off
from 5 to 60 seconds. Failed images can be fetched by rerunning the command.

BG-20k writes `data/bg-20k/images/{train,testval}/<file>` and a `metadata.csv` with
`filename,split` columns, matching the dev pool. It reuses an archive already downloaded
under the output directory, restores missing images on reruns, and removes the archive
copy only after every file named by the split lists is present. Missing files or differing
copies of the same filename within a split stop the run and keep the archive. Identical
copies across shards are accepted; names in different splits remain separate.
Use `data/magick` and `data/bg-20k` as Stage A's source roots.

**Neither source needs an account.** MAGICK comes from Hugging Face over plain HTTPS.
kagglehub signs in only for private datasets or ones that ask for consent. With no Kaggle
credentials on the machine, kagglehub fetches single BG-20k files and the 13.1 GiB archive.
If Kaggle ever refuses an anonymous download, create an API token at
[kaggle.com/settings](https://www.kaggle.com/settings), save it as `~/.kaggle/access_token`,
and run the command again. kagglehub still reads a legacy `~/.kaggle/kaggle.json` too.

---

## Library names

Libraries live in two sibling roots, named like the pools: `data/library/<estimator>` for
the full pools (`magick` and `bg-20k`), and `data/library_dev/<estimator>` for the dev pools
(`magick_dev` and `bg-20k_dev`). Estimator names have no suffix in either root. Build the
full library after downloading the full pools above, or build the dev library from the
pools a fresh clone carries:

```bash
# Full pools: the library for the final dataset
uv run --frozen --no-sync python -m video_bokeh.library.build \
  --fg-data-root data/magick --bg-data-root data/bg-20k \
  --output data/library/da2-large --size 1024 --model da2-large

# Dev pools: the library for the demo and examples
uv run --frozen --no-sync python -m video_bokeh.library.build \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output data/library_dev/da2-large --size 1024 --model da2-large
```

The recipes below use the dev library. For the final dataset, pass
`--library-root data/library/da2-large` to Stage B instead.

**Existing checkouts.** From the repository root, move one dev library at a time:

1. Count its assets. A dev library uses the tracked dev pools: at most 30 foregrounds
   and 30 backgrounds. A full library has thousands: about 8,586 foregrounds and
   20,000 backgrounds. Leave every library with thousands of assets in place.
   Replace `<name>` with the estimator name, or the estimator plus `-dev` if
   a `-dev` suffix was applied.

   ```bash
   ls backend/data/library/<name>/foregrounds | wc -l
   ls backend/data/library/<name>/backgrounds | wc -l
   ```

2. Create the parent directory, then make sure `backend/data/library_dev/<estimator>`
   does not exist. If it exists, stop to avoid nesting libraries.

   ```bash
   mkdir -p backend/data/library_dev
   ```

3. Move only a library identified as dev in step 1, using the unsuffixed estimator
   name for `<estimator>`:

   ```bash
   mv backend/data/library/<name> backend/data/library_dev/<estimator>
   ```

## 1. Stage A: build the library

Run the matching build command in [Library names](#library-names).

**`--size` need not match Stage B.** Stage B maps each asset onto the frame whatever its
size. A library smaller than the frame is only upscaled, and looks softer for it.

**The CLIP filter drops assets.** Stage A keeps only foregrounds whose predicted subject and
style are among `--subjects` and `--styles`, and whose subject score is at least
`--subject-thr`, so the dev pool's 30 foregrounds yield 17 in the library. Pass
`--subjects "" --styles "" --subject-thr 0` to turn it off; any one of them alone leaves the
other two filtering.

A fast check with no large download (3 foregrounds, 2 backgrounds, the small model) takes
**6.7 s** on an M-series Mac using `mps`:

```bash
uv run python -m video_bokeh.library.build \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output /tmp/lib_smoke --size 256 --model da2-small \
  --limit-fg 3 --limit-bg 2
```

---

## 2. Stage B: generate sequences

```bash
uv run python -m video_bokeh.scenes.generate \
  --library-root data/library_dev/da2-large --output data/demo \
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
  --library-root data/library_dev/da2-large --output data/demo5 \
  --count 3 --frames 8 --size 512 --n-objects-min 5 --n-objects-max 5
```

What binds now is the depth axis, not the image format. Objects get disjoint slots above the
background, so each extra object narrows every slot and makes collisions harder to avoid. Five
places every scene; six starts losing them. The measured sweep is in
[check-trajectories-by-eye](check-trajectories-by-eye.md), and
[dataset-layout](../reference/dataset-layout.md) says what to raise if you need more.

### Optical flow

`--flow` writes each frame's exact forward optical flow to the next into `flow/`, in the same
pass as the frames:

```bash
uv run python -m video_bokeh.scenes.generate \
  --library-root data/library_dev/da2-large --output data/demo_flow \
  --count 3 --frames 80 --size 512 --seed 0 --flow
```

With the old PNG compression default, level 6, it took 20 s on an Apple M3 Pro, against
14 s for the same three sequences without `--flow`. Each sequence's `flow/` held 79 files,
2.2 to 3.5 MiB in all. The writer now uses level 3. On a 512 px sequence, it saved 26.6% of
writer time and used 2.67 MiB instead of 1.71 MiB, with identical decoded pixels.
[dataset-layout](../reference/dataset-layout.md#the-flow-stream-optional) has the format and
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
budget and held their start scale instead. Expect `0`, and treat anything else as a sign the
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
[check-trajectories-by-eye](check-trajectories-by-eye.md).

---

## 5. Render bokeh

**One run writes the frames and their bokeh**, with the layered renderer that
[layered-bokeh](../explanation/layered-bokeh.md) explains. It runs on any machine with torch
installed.

```bash
uv run python -m video_bokeh.scenes.generate \
  --library-root data/library_dev/da2-large --output data/demo_bokeh \
  --count 2 --frames 24 --size 512 --seed 0 --bokeh
```

It took 7 s on an Apple M3 Pro.

**The renderer can also draw the bokeh again over sequences already written**, from the layers
Stage B wrote with `--layers`. This step is optional:

```bash
uv run python -m video_bokeh.scenes.generate \
  --library-root data/library_dev/da2-large --output data/demo_layers \
  --count 2 --frames 24 --size 512 --seed 0 --layers
uv run --extra render python -m video_bokeh.render.run --data-root data/demo_layers \
  --renderer layered
```

The render took 3 s on an Apple M3 Pro.

---

## Clean up

```bash
rm -rf data/demo data/demo5 data/demo_bokeh data/demo_layers
```
