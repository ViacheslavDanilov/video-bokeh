# Dataset Generation

Two-stage pipeline. All commands run from `backend/`.

---

## Stage A — Build the library

Runs the depth estimator once per asset. Slow (GPU recommended). Results are reusable.

```bash
uv run python -m data.build_library \
  --fg-data-root data/magick_dev \
  --bg-data-root data/bg-20k_dev \
  --output       data/library_dev \
  --size 1024 \
  --model da2-large \
  --low-pct 2.0
```

### Key flags

| Flag | Default | Notes |
|---|---|---|
| `--fg-data-root` | required | MAGICK foreground images root |
| `--bg-data-root` | required | BG-20k background images root |
| `--output` | required | Library output directory |
| `--size` | `1024` | Square frame size in pixels |
| `--model` | `da2-large` | Depth estimator (`da2-base`, `da2-large`) |
| `--low-pct` | `2.0` | Drop trusted-core pixels below this percentile (depth holes). Set to `0` to disable. |
| `--limit-fg` | — | Cap number of foregrounds (useful for testing) |
| `--limit-bg` | — | Cap number of backgrounds |

### Output per foreground asset

```
library_dev/foregrounds/<id>/
├── rgb.png        # RGBA cut-out
├── alpha.png      # Alpha mask (uint8)
├── depth.png      # Propagated disparity (uint16)
├── depth_raw.png  # Raw estimator output before propagation (uint16, diagnostic)
└── meta.json      # Depth stats: core_frac, n_low_outliers, low_confidence, …
```

---

## Stage B — Generate sequences

No GPU needed. Samples scenes from the library and writes frame sequences.

### Fixed slots (safe baseline)

```bash
uv run python -m data.generate_dataset \
  --library-root data/library_dev \
  --output       data/synth_fixed \
  --count 5 --frames 80 --size 1024 --seed 0
```

### Dynamic depth (z(t) tracks + collision validation)

```bash
uv run python -m data.generate_dataset \
  --library-root data/library_dev \
  --output       data/synth_dynamic \
  --count 5 --frames 80 --size 1024 --seed 0 \
  --depth-mode dynamic
```

### Key flags

| Flag | Default | Notes |
|---|---|---|
| `--library-root` | required | Output of Stage A |
| `--output` | required | Dataset output directory |
| `--count` | `5` | Number of sequences |
| `--frames` | `80` | Frames per sequence |
| `--size` | `1024` | Square frame size in pixels |
| `--seed` | `0` | Global random seed |
| `--n-objects-min` | `1` | Min foreground objects per scene |
| `--n-objects-max` | `3` | Max foreground objects per scene |
| `--depth-mode` | `fixed` | `fixed` = disjoint slots; `dynamic` = z(t) tracks + validator |

### Output layout

```
synth_dynamic/
├── manifest.csv
└── sequences/
    └── 0001/
        ├── all_in_focus/<frame>.png
        ├── alpha/<frame>.png
        └── disparity/<frame>.png
```

### manifest.csv columns

`seq_id`, `seed`, `n_frames`, `size`, `n_objects`, `depth_mode`, `n_rejections`

`n_rejections` counts how many times the collision validator resampled a scene. Consistently high values (> 10) indicate the motion ranges are too aggressive — lower `_Z_NEAR`/`_Z_FAR` in `src/data/compositor.py` or increase `margin` in `src/data/_collision.py`.

---

## Quick smoke test (no GPU)

```bash
uv run python -m data.build_library \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output /tmp/lib_smoke --size 256 --model da2-base \
  --limit-fg 3 --limit-bg 1

uv run python -m data.generate_dataset \
  --library-root /tmp/lib_smoke --output /tmp/synth_smoke \
  --count 4 --frames 10 --size 256 --depth-mode dynamic
```

---

## Visualize with vpv

`vpv` opens an N-pane viewer with synchronized playback. Run from inside the dataset's `sequences/` directory.

```bash
cd backend/data/synth_dynamic/sequences
vpv "*/all_in_focus/*.png" "*/alpha/*.png" "*/disparity/*.png"
```

To compare fixed vs dynamic side by side (run from repo root):

```bash
vpv \
  'backend/data/synth_fixed/sequences/*/all_in_focus/*.png' \
  'backend/data/synth_dynamic/sequences/*/all_in_focus/*.png' \
  'backend/data/synth_dynamic/sequences/*/disparity/*.png'
```

---

## Prepare for any-to-bokeh inference

```bash
uv run python -m data.prepare_any_to_bokeh --data-root data/synth_dynamic
```
