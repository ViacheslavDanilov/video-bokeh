---
type: how-to
status: active
tags: [how-to, demo, colormap, multi-object, runbook]
related: [cli, dataset-layout, generate-a-dataset, demo-unrestricted-trajectories]
---

# Demo: four and five objects, colour disparity, multi-page alpha

This pipeline generates scenes with four and five objects, renders disparity as a red-near,
blue-far colour video instead of grey, and stores alpha as one TIFF page per object. This
recipe reproduces all three from a clean checkout, with every artifact written under `/tmp` so
it never touches `backend/data/`.

Every command below was executed as written on this machine (Apple Silicon, `mps`). Commands
run from `backend/`, except the `uv sync` below, which runs from the repo root.

---

## Before you start

Install both extras this recipe needs: `library` for Stage A, `preview` for the video packer.
Run this one from the repo root, not `backend/`:

```bash
uv sync --all-extras --dev
```

You need the tracked dev pools, already in the repo: `data/magick_dev` (12 usable foregrounds
out of 20, the rest dropped by the CLIP subject filter) and `data/bg-20k_dev` (20 backgrounds).
No download, no Kaggle credentials.

---

## 1. Build the library (Stage A)

```bash
cd backend
uv run python -m video_bokeh.library.build \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output /tmp/vb-demo/library --size 512 --model da2-small
```

**10.25 s.** `da2-small` is the fast depth model; `da2-large` is the default and slower. This
recipe uses `da2-small` because the demo is about the colormap and the object count, not depth
fidelity, and a fast Stage A is what makes the recipe reproducible on a fresh clone in under a
minute rather than several.

## 2. Generate four- and five-object scenes (Stage B)

The scene sampler rejects layouts where two objects overlap on screen while their depth ranges
overlap, and retries. More objects means more retries, so the number that matters here is not
how many sequences were requested but how many actually came out.

```bash
cd backend
uv run python -m video_bokeh.scenes.generate \
  --library-root /tmp/vb-demo/library --output /tmp/vb-demo/synth_4obj_n20 \
  --count 20 --frames 80 --size 512 --seed 300 \
  --n-objects-min 4 --n-objects-max 4
```

```bash
cd backend
uv run python -m video_bokeh.scenes.generate \
  --library-root /tmp/vb-demo/library --output /tmp/vb-demo/synth_5obj_n20 \
  --count 20 --frames 80 --size 512 --seed 400 \
  --n-objects-min 5 --n-objects-max 5
```

Measured, including an earlier 10-sequence batch at each count (seeds 100 and 200) run the same
way:

| objects | requested | generated | sec/sequence |
|---|---|---|---|
| 4 | 30 | 30 | 6.55 |
| 5 | 30 | 30 | 8.84 |

**Every one of the 60 requested sequences came out; none were skipped.** Five-object scenes
cost 35 % more wall-clock time per sequence than four-object scenes (8.84 s against 6.55 s),
which matches the collision validator needing more retries as the depth slots narrow, but on
this library (12 foregrounds, 20 backgrounds) that extra cost never became a dropped sequence.
This is measured on the small tracked dev pool; a bigger asset library changes the retry
arithmetic and is worth re-checking before relying on the same reliability at scale.

The demo videos below come from a third, smaller run mixing both counts:

```bash
cd backend
uv run python -m video_bokeh.scenes.generate \
  --library-root /tmp/vb-demo/library --output /tmp/vb-demo/synth_demo \
  --count 6 --frames 80 --size 512 --seed 0 \
  --n-objects-min 4 --n-objects-max 5
```

**44.17 s, 6 of 6 sequences generated:** `0001` and `0004`/`0005` at 4 objects, `0002`/`0003`/`0006`
at 5 objects.

## 3. Pack both streams to video

```bash
cd backend
uv run python -m video_bokeh.preview.pack \
  --data-root /tmp/vb-demo/synth_demo --streams all_in_focus,disparity \
  --colormap spectral_r --fps 24
```

**5.14 s** for 6 sequences, 2 streams, 80 frames each. Output: `all_in_focus.mp4` and
`disparity.mp4` next to each sequence's PNG streams, e.g.
`/tmp/vb-demo/synth_demo/sequences/0002/disparity.mp4`.

## 4. Verify alpha is one TIFF page per object

For every sequence in `synth_demo`, `read_alpha_tiff` (`src/video_bokeh/core/_streams.py`) reads
back the page count and it matches the object count Stage B printed, on both the first and the
last frame:

| sequence | objects (from Stage B log) | TIFF pages, frame 1 | TIFF pages, frame 80 |
|---|---|---|---|
| 0001 | 4 | 4 | 4 |
| 0002 | 5 | 5 | 5 |
| 0003 | 5 | 5 | 5 |
| 0004 | 4 | 4 | 4 |
| 0005 | 4 | 4 | 4 |
| 0006 | 5 | 5 | 5 |

Every mask is `(512, 512)` `float32`, and the page count never drifts between the first and
last frame of a clip.

## 5. Watch the videos

`disparity.mp4` is genuinely colour, not a grey ramp with a palette applied at display time: on
a sampled frame the red and blue channels differ by up to 180 out of 255, with a mean channel
gap of 79.5 across the frame. The background reads deep blue-violet (far) and foreground
subjects read orange to red (near), matching `Spectral_r` reversed so red is near.

Motion through depth shows up as a colour change, not a still image. On sequence `0002` (5
objects), the mean disparity under each object's own alpha mask across all 80 frames moves by:

| object | disparity at frame 1 | disparity at frame 80 | range over the clip |
|---|---|---|---|
| 0 | 0.204 | 0.899 | 0.747 |
| 1 | 0.283 | 0.146 | 0.359 |
| 2 | 0.676 | 0.203 | 0.473 |
| 3 | 0.700 | 0.898 | 0.198 |
| 4 | 0.861 | 0.686 | 0.175 |

Object 0 alone crosses three-quarters of the disparity range, which reads on screen as that
object sliding from teal-green at the start of the clip to deep red by the end: the colour
carries the depth motion, so a viewer sees the object approach without needing the alpha or
depth streams open next to it.

---

## Artifacts

Everything below is under `/tmp/vb-demo` and was left in place:

- `library/` — Stage A output, 12 foregrounds, 20 backgrounds
- `synth_demo/` — the 6-sequence demo dataset, with `all_in_focus.mp4` and `disparity.mp4`
  packed for each sequence
- `synth_4obj_n20/`, `synth_5obj_n20/` — the 20-sequence reliability batches at four and five
  objects
- `synth_4obj/`, `synth_5obj/` — the earlier 10-sequence batches at the same two counts

These stay under `/tmp` deliberately, for the 2026-09-22 meeting to open directly; nothing here
runs a cleanup step.
