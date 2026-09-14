---
type: topic
status: active
tags: [topic, datasets, pipeline, depth, bokeh]
---

# Synthetic data pipeline — how to run

We build training videos in two steps: estimate depth once per object and background, then composite those pieces into videos on the fly. Depth is never re-run per frame. See [[meetings/2026-06-03-layer-depth-onthefly-pipeline]] for the why.

All commands run from `backend/`. Output lives under `backend/data/`, which is gitignored.

## The two stages

1. **Stage A — build the artifact library** (`build_library`). Cut each foreground object out, paste it on a neutral background, run the depth model once, and spread that depth across the whole frame. Run the depth model once on each background too. This is the slow, neural step.
2. **Stage B — generate sequences** (`generate_dataset`). Sample a few objects and a background from the library, move them with smooth motion, and composite their colour, mask, and depth into a video. This is fast and produces a fresh dataset each time.

## Prerequisites

- Foregrounds downloaded to `data/magick_dev` (see [[magick]]).
- Backgrounds downloaded to `data/bg-20k_dev` (see [[datasets]]).
- Dependencies installed: `uv sync --dev` from the repo root.

## Recipe — default run

```bash
# Stage A: build the library (depth runs once per asset)
uv run python -m data.build_library \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output data/my_run/library --size 512 --model da2-large

# Stage B: generate sequences from the library
uv run python -m data.generate_dataset \
  --library-root data/my_run/library --output data/my_run/dataset \
  --count 10 --frames 80 --size 512 --seed 0
```

## Recipe — 1024×1024

Use the same two commands with `--size 1024` in **both**. The size must match across the two stages, because Stage B warps the library's images and they have to start at the frame resolution.

```bash
# Stage A at 1024
uv run python -m data.build_library \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output data/pipeline_test_1024/library --size 1024 --model da2-large

# Stage B at 1024
uv run python -m data.generate_dataset \
  --library-root data/pipeline_test_1024/library --output data/pipeline_test_1024/dataset \
  --count 5 --frames 24 --size 1024 --seed 0
```

## Key flags

- **`--size`** — frame resolution in pixels. Must be identical in both stages.
- **`--model`** — depth model. `da2-large` for quality (one-time ~1.3 GB download, a few minutes on the Mac for ~30 assets), `da2-small` for a fast check.
- **`--count`** — number of sequences to generate.
- **`--frames`** — frames per sequence.
- **`--seed`** — fixed seed gives the same dataset every run.

## Decisions and gotchas

- **Both stages need the same `--size`.** Mismatched sizes warp the wrong-sized depth maps into the frame and corrupt the output.
- **Stage A is the expensive one.** Build the library once, then run Stage B as many times as you like; each run is a fresh dataset from the same assets.
- **The CLIP filter drops some foregrounds.** Stage A keeps only objects whose predicted subject and style pass a threshold, so 20 input objects may yield about 12 in the library. Pass `--subjects ""` to turn the filter off.
- **`da2-large` at 1024 is about 7× the pixels of a 384 run**, so expect proportionally more time and disk.

## Outputs

```
data/my_run/
├── library/                       # Stage A
│   ├── foregrounds/<id>/{rgb.png, alpha.png, depth.png}   # depth is uint16 PNG
│   └── backgrounds/<id>/{rgb.png, depth.png}
└── dataset/                       # Stage B
    ├── manifest.csv
    └── sequences/<id>/{all_in_focus, alpha, disparity}/*.png
```

Then hand the dataset to the bokeh renderer:

```bash
uv run python -m data.prepare_any_to_bokeh --data-root data/my_run/dataset
```

## Viewing results

From the dataset's sequences folder, view colour, mask, and depth side by side with `vpv`:

```bash
cd data/my_run/dataset/sequences
vpv "*/all_in_focus/*.png" "*/alpha/*.png" "*/disparity/*.png"
```

## Cross-references

- Meeting that set this design: [[meetings/2026-06-03-layer-depth-onthefly-pipeline]].
- Earlier pipeline spec: [[specs/2026-05-27-layer-wise-depth-bokeh-pipeline]].
- Datasets index: [[datasets]].
