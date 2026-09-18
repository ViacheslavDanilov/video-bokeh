---
type: how-to
status: active
tags: [how-to, unrestricted-trajectories, demo, vpv, runbook]
related: [pipeline-explainer, generate-a-dataset, dataset-layout]
---

# Check the trajectory model by eye

How to convince yourself the depth trajectories are right, using `vpv`.

There used to be a second depth mode to compare against. There is only one now, so the
comparison is against the **claim** instead: each object moves freely through depth, and its
disparity moves *with* its apparent size. An object that grows on screen must get brighter in
the disparity stream, and two objects that cross must swap which one is drawn in front.

Commands run from `backend/` unless stated. Output lands in `backend/data/`, which is
gitignored. To produce a dataset in the first place, see [[generate-a-dataset]].

---

## Before you start

You need the artifact library. If `backend/data/library_dev/` already has `foregrounds/` and
`backgrounds/`, skip this — the current one holds 12 foregrounds and 20 backgrounds, enough
for every recipe here.

```bash
cd backend
uv run python -m data.build_library \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output data/library_dev --size 1024 --model da2-large
```

---

## 1. The main check: does disparity follow size

```bash
cd backend
uv run python -m data.generate_dataset \
  --library-root data/library_dev --output data/demo \
  --count 4 --frames 80 --size 512 --seed 0
```

```bash
cd data/demo/sequences
vpv "*/all_in_focus/*.png" "*/disparity/*.png"
```

**What to look for.** Scrub the clip and watch both panes together.

- An object's grey level tracks its size. As it grows, it brightens; as it shrinks, it darkens.
- **The direction is the entire point.** An object that grows on screen while its patch gets
  *darker* means the depth-scale law inverted, and everything downstream is wrong. The law is
  `ratio = scale_end / scale_start`; [[pipeline-explainer]] explains why the reciprocal, which
  the research spec writes, is the error.
- An object approaching also spreads over a *wider* band of grey, because its whole disparity
  interval scales with it. That is correct, not a bug.

---

## 2. Object count

The slot that seeds frame 1 gets narrower as objects are added, so crowding is what stresses
the collision validator.

```bash
cd backend
for n in 1 2 3; do
  uv run python -m data.generate_dataset \
    --library-root data/library_dev --output "data/demo_n$n" \
    --count 4 --frames 80 --size 512 --seed 0 \
    --n-objects-min $n --n-objects-max $n
done
```

```bash
cd backend/data/demo_n3/sequences
vpv "*/all_in_focus/*.png" "*/disparity/*.png"
```

**What to look for.**

- Two objects may overlap on screen, but never while sharing a depth. When their outlines
  cross, one is unambiguously in front.
- Each object keeps its own alpha page for the whole clip. A mask that jumps between pages
  mid-clip is a bug. `vpv` renders only a TIFF's first page, so read the alpha stream with
  `read_alpha_tiff` from `src/data/_streams.py` instead of looking at it.
- Paint order is recomputed per frame, so a pair that swaps depth also swaps which one
  occludes the other. Expect to see it at three objects.

Measured on this library, 12 scenes per count at 40 frames and size 256:

| objects | slot width | skipped | mean rejections | sec/scene |
|---|---|---|---|---|
| 1 | 0.950 | 0 | 0.00 | 0.08 |
| 2 | 0.465 | 0 | 0.25 | 0.22 |
| 3 | 0.303 | 0 | 0.42 | 0.31 |
| 4 | 0.222 | 0 | 0.83 | 0.45 |
| 5 | 0.174 | 0 | 5.17 | 1.12 |
| 6 | 0.142 | 2 | 8.75 | 2.18 |
| 8 | 0.101 | 11 | 1.42 | 3.48 |

Rejections climb steeply past four objects, and past five the axis starts losing scenes
outright. The low rejection count at eight is an artifact: most scenes hit the retry cap and
were skipped rather than counted.

---

## 3. Seeds and length

Sequence names are tied to the seed: sequence `i` always comes from `seed + i`. A sequence
whose trajectories cannot be made collision-free is skipped, which leaves a gap in the
numbering rather than shifting every later sequence onto a different seed.

```bash
cd backend
uv run python -m data.generate_dataset \
  --library-root data/library_dev --output data/demo_seeds \
  --count 10 --frames 80 --size 512 --seed 100
```

If the run prints `Skipped N of 10 sequences`, the named seeds are the crowded ones. That is
the validator refusing to emit an ambiguous sample, not a failure.

Recipe 1 as written took **14.9 s**. For a full-resolution look, raise `--size` to 1024.

---

## 4. Read the manifest

```bash
cd backend
column -s, -t < data/demo/manifest.csv
```

| column | meaning |
|---|---|
| `n_rejections` | trajectory sets discarded because two objects collided. Rises with object count |
| `n_range_fallbacks` | objects whose end pose could not be sampled within the retry budget and fell back to holding their start scale. Expect `0`; anything else means the depth axis is unusually tight, which needs `bg_band_top` raised through the Python API, since the CLI does not expose it |

Every column: [[dataset-layout]].

---

## 5. Bridge to any-to-bokeh

```bash
cd backend
uv run python -m data.prepare_any_to_bokeh --data-root data/demo
```

See [[run-any-to-bokeh-inference]].

---

## Cleaning up

```bash
cd backend
rm -rf data/demo data/demo_n1 data/demo_n2 data/demo_n3 data/demo_seeds
```
