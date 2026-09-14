# Unrestricted trajectories — demo

How to exercise the `unrestricted` depth mode and judge the result by eye in `vpv`.

The claim under test: each object now moves freely through depth, and its disparity moves *with* its apparent size. An object that grows on screen must get brighter in the disparity stream, and two objects that cross must swap which one is drawn in front.

Every command runs from `backend/` unless it says otherwise. Outputs land in `backend/data/`, which is gitignored.

---

## Before you start

You need the artifact library. If `backend/data/library_dev/` already has `foregrounds/` and `backgrounds/`, skip this.

```bash
cd backend
uv run python -m data.build_library \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output data/library_dev --size 1024 --model da2-large
```

The current `library_dev` holds 12 foregrounds and 20 backgrounds, which is enough for every recipe here.

---

## 1. The main comparison: fixed vs unrestricted, same seed

This is the one to run first. The same seed gives both runs the same background and the same foreground objects, because those are drawn before any trajectory is built. The motion itself differs: the unrestricted branch consumes extra random draws while rejecting end poses, and it orders objects by depth rather than by slot. So this is an A/B of the two depth models on the same assets, not the same clip rendered twice.

```bash
cd backend
uv run python -m data.generate_dataset \
  --library-root data/library_dev --output data/demo_fixed \
  --count 4 --frames 80 --size 512 --seed 0 --depth-mode fixed

uv run python -m data.generate_dataset \
  --library-root data/library_dev --output data/demo_unrestricted \
  --count 4 --frames 80 --size 512 --seed 0 --depth-mode unrestricted
```

View them side by side, from the repo root:

```bash
vpv \
  'backend/data/demo_fixed/sequences/*/all_in_focus/*.png' \
  'backend/data/demo_fixed/sequences/*/disparity/*.png' \
  'backend/data/demo_unrestricted/sequences/*/all_in_focus/*.png' \
  'backend/data/demo_unrestricted/sequences/*/disparity/*.png'
```

**What to look for.** Scrub through the clip and watch panes 2 and 4.

- In `fixed`, an object's grey level barely moves: it is pinned inside its depth slot for the whole clip.
- In `unrestricted`, the grey level tracks the object's size. As it grows, it brightens; as it shrinks, it darkens.
- The direction is the whole point. If an object grows on screen while its patch gets *darker*, the depth-scale law is inverted and something regressed.

---

## 2. Object count

The band that seeds frame 1 gets narrower as objects are added, so crowding is what stresses the collision validator.

```bash
cd backend
for n in 1 2 3; do
  uv run python -m data.generate_dataset \
    --library-root data/library_dev --output "data/demo_n$n" \
    --count 4 --frames 80 --size 512 --seed 0 \
    --n-objects-min $n --n-objects-max $n --depth-mode unrestricted
done
```

View one count at a time, from inside its `sequences/` directory:

```bash
cd backend/data/demo_n3/sequences
vpv "*/all_in_focus/*.png" "*/alpha/*.png" "*/disparity/*.png"
```

**What to look for.**

- Two objects may overlap on screen, but never while sharing a depth. When their outlines cross, one is unambiguously in front.
- Watch the alpha pane. Each object keeps its own colour channel for the whole clip: object 1 is red, object 2 is green, object 3 is blue. A mask that jumps between channels mid-clip is a bug.
- Paint order is recomputed per frame, so a pair that swaps depth also swaps which one occludes the other. Expect to see it at three objects.

Measured on this library, 6 scenes per count at 40 frames and size 512:

| objects | slot width | rejections | skipped | disparity |
|---|---|---|---|---|
| 1 | 0.950 | 0 | 0 | 0.000–0.946 |
| 2 | 0.465 | 1 | 0 | 0.000–0.909 |
| 3 | 0.303 | 2 | 0 | 0.000–0.976 |

Rejection counts climb steeply past three objects: five objects cost 27 rejections over the same six scenes.

---

## 3. The object limit is enforced, not silent

The alpha stream is a single RGB PNG, so it carries exactly three masks. Asking for more used to write the first three and drop the rest without a word. It now refuses:

```bash
cd backend
uv run python -m data.generate_dataset \
  --library-root data/library_dev --output data/demo_toomany \
  --count 1 --frames 8 --size 256 --n-objects-max 4 --depth-mode unrestricted
```

Expected, and nothing written:

```
generate_dataset.py: error: n_objects_max=4 but the alpha stream holds 3 masks;
every object past the third would be present in all_in_focus and disparity but
absent from alpha. Lifting the limit needs a multi-channel alpha format.
```

Lifting the limit is a format change — multi-channel TIFF or NumPy — and is deferred to the next version.

---

## 4. Seeds and length

Sequence names are tied to the seed: sequence `i` always comes from `seed + i`. A sequence whose trajectories cannot be made collision-free is skipped, which leaves a gap in the numbering rather than shifting every later sequence onto a different seed.

```bash
cd backend
uv run python -m data.generate_dataset \
  --library-root data/library_dev --output data/demo_seeds \
  --count 10 --frames 80 --size 512 --seed 100 --depth-mode unrestricted
```

If the run prints `Skipped N of 10 sequences`, the named seeds are the crowded ones. That is the validator refusing to emit an ambiguous sample, not a failure.

Recipe 1 as written (4 sequences, 80 frames, size 512) took 12.5 s in `fixed` and 13.9 s in `unrestricted` on this machine. The difference is the collision validator, which warps every object's mask on every frame and pays that cost again for each rejected attempt.

For a full-resolution look, raise `--size` to 1024. Budget roughly 3 seconds per scene for trajectory sampling alone at 3 objects and 80 frames, before any rendering.

---

## 5. Read the manifest

`manifest.csv` records what each sequence cost to sample.

```bash
cd backend
column -s, -t < data/demo_unrestricted/manifest.csv
```

| column | meaning |
|---|---|
| `n_rejections` | trajectory sets discarded because two objects collided. Rises with object count. |
| `n_range_fallbacks` | objects whose end pose could not be sampled within the retry budget and fell back to holding their start scale. Expected to be 0; a non-zero value means the depth axis is unusually tight, typically from a raised `--bg-band-top`. |
| `depth_mode` | which model produced the sequence. |

---

## 6. Bridge to any-to-bokeh

Once a batch looks right, convert it for inference:

```bash
cd backend
uv run python -m data.prepare_any_to_bokeh --data-root data/demo_unrestricted
```

---

## Cleaning up

```bash
cd backend
rm -rf data/demo_fixed data/demo_unrestricted data/demo_n1 data/demo_n2 data/demo_n3 data/demo_seeds
```
