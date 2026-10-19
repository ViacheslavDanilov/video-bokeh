# Comparison with other bokeh renderers

Scripts that run published bokeh renderers on our sequences and score their output against
ours. **None of those methods' code is in this repository.** `setup.sh` clones a pinned commit
of each into `third_party/` and builds its environment under `envs/`; both, and the tools that
build them, are ignored by git. What is tracked here is ours: the setup recipe, an adapter per
method that reads our sequence layout and writes `bokeh_<method>/` beside `bokeh/`, and the
scoring.

The methods run on a machine with an NVIDIA card. On the lab's RTX 5090, torch needs the CUDA
12.8 wheels, which the methods' own pins (torch 1.8 to 2.4) predate, so each method gets a
rebuild on a current torch with a small patch where its source calls something that torch
removed. The inputs, licenses and difficulty of each candidate method were surveyed on
2026-10-15; the survey is among the author's local notes.

## Dr.Bokeh

[Dr.Bokeh](https://github.com/ShengCN/DrBokeh-Src) (CVPR 2024) is a layer renderer: it takes
layers with color, alpha and per-pixel disparity, as ours are, and needs no weights. Its code
has no license file, so it stays on the machine that runs it and is not redistributed.

```bash
comparison/setup.sh drbokeh
# Sequences written with layers and bokeh, so that there is a focus record to match:
cd backend && uv run python -m video_bokeh.scenes.generate \
  --library-root data/library/da2-large --output data/cmp --count 5 --frames 24 --size 1024 \
  --seed 0 --layers --bokeh
cd .. && comparison/envs/render/bin/python comparison/run_drbokeh.py --data-root backend/data/cmp
comparison/envs/render/bin/python comparison/score.py --data-root backend/data/cmp --method drbokeh
```

`run_drbokeh.py` gives Dr.Bokeh the same layers, the same focus disparity per frame and the
same strength as our renderer used, from the sequence's `bokeh/focus.json`. Strength is its
`K`, the blur radius in pixels at one unit of disparity from the focus, so it is ours scaled to
the frame's width. Each object layer's disparity, which we store only under its alpha, is
extended outward from the nearest pixel under it, because Dr.Bokeh reads the disparity of
pixels with no alpha to size the blur at an edge.

The two renders are not the same algorithm, and the score measures that difference. Ours
blurs in linear light and composites in gamma values, and Dr.Bokeh composites in linear light
and returns to gamma values once, both with the power of 2.2. Dr.Bokeh's radius is
`K|d - zf| + 1`, so an in-focus pixel still spreads a small disk.

`score.py` writes `comparison_drbokeh.json` with, per frame, the PSNR and the mean absolute
difference over the whole frame and over a band around the object edges, where a layered and a
single-layer renderer part. The band is the square of 16 pixels around every edge of every
object's alpha mask.

## MPIB's ray tracer

The generator behind MPIB's training data
([MPIB](https://github.com/JuewenPeng/MPIB), ECCV 2022, Sec. 3.4, "Bokeh Generator and Training
Data"; Apache-2.0) traces rays
through a thin lens and the layers, which makes it the closest thing to a ray-traced reference
for a layered renderer. It takes no weights.

```bash
comparison/setup.sh mpib
comparison/envs/render/bin/python comparison/run_mpib_rt.py --data-root backend/data/cmp
comparison/envs/render/bin/python comparison/score.py --data-root backend/data/cmp --method mpib_rt
```

It reads the same layers, focus and strength as `run_drbokeh.py`, and writes `bokeh_mpib_rt/`.
Its layers differ in one respect that decides what the score can say: each layer is an alpha
mask and one plane, `Z = C + A X + B Y` in depth, not a disparity map. `planes.py` fits each
layer's plane to its disparity under its alpha, by least squares, so the relief inside an
object is lost. That is why this render is a reference for the edges and the occlusion, where
layers decide the result, and not for the blur inside an object, which our renderer and
Dr.Bokeh's keep per pixel. The lens radius `K` is in pixels per unit of disparity from the
focus, which is our strength scaled to the frame's width, and the focus goes in as a depth.

## BokehMe

[BokehMe](https://github.com/JuewenPeng/BokehMe) (CVPR 2022; Apache-2.0) is a single-image
method: a classical scatter renderer, and two networks, whose weights ship in its repository,
that repair the scatter where it is wrong. It takes one image and one disparity map and cannot
take layers, so it must guess what an object hides. It is a comparator and not a reference.

```bash
comparison/setup.sh bokehme
comparison/envs/render/bin/python comparison/run_bokehme.py --data-root backend/data/cmp
comparison/envs/render/bin/python comparison/score.py --data-root backend/data/cmp --method bokehme
comparison/envs/render/bin/python comparison/score.py --data-root backend/data/cmp --method bokehme_classical
```

`run_bokehme.py` reads each frame's `all_in_focus/` and `disparity/` and the focus and strength
that our renderer recorded, and writes two streams: `bokeh_bokehme/`, the hybrid, and
`bokeh_bokehme_classical/`, the scatter alone, which shows what the networks repair. It runs
BokehMe's own `pipeline` function, read from its `demo.py` without the command line. The demo
reads the disparity at 8 bits and rescales it to `[0, 1]` per image. Here the disparity keeps
its 16 bits and its scale, because the focus our renderer recorded is on that scale, and
`gamma` is 2.2, as for our renderer.

## Any-to-Bokeh

[Any-to-Bokeh](https://github.com/vivoCameraResearch/any-to-bokeh) (ICLR 2026; code and
weights CC BY-NC 4.0) is a video diffusion model, which this pipeline carried as a bokeh
renderer until 2026-10-15. It is the learned baseline of the comparison, not a reference. It
needs an environment of its own, Python 3.10 with the `diffusers` and `transformers` versions
that its requirements pin, 6.7 GB of checkpoints from Google Drive and the Stable Video Diffusion base
model, 4.2 GiB under Stability's own license, which `setup.sh` downloads into the Hugging
Face cache.

```bash
comparison/setup.sh a2b
comparison/envs/render/bin/python comparison/run_any_to_bokeh.py --data-root backend/data/cmp
comparison/envs/render/bin/python comparison/score.py --data-root backend/data/cmp --method any_to_bokeh
```

`run_any_to_bokeh.py` writes the demo's inputs, a folder of frames and a folder of 8-bit
disparity maps per sequence, with each frame's focus in the file name, and runs the demo
through `a2b_launch.py`, which has the video model's encoder take a few frames at a time so
that it fits a 32 GiB card. The focus and the strength are the ones our renderer recorded.
Three things make its output differ from ours for reasons other than the model: the demo works
at 1024 x 576, so our square frames are stretched and its blur is 1.78 times taller than wide;
it writes a lossy H.264 video, whose frames are resized back to the sequence's size; and the
disparity is quantized to 8 bits. It takes sequences of 13 frames or more.

## All methods at once

After `setup.sh` has built each method, one command runs them all over written sequences,
scores each against our bokeh and prints a table:

```bash
comparison/run_all.sh backend/data/cmp
```

The sequences must hold their layers and our bokeh, so that every method gets the focus and
the strength that our renderer recorded. The command stops before it starts if a method is not
set up. `summary.py` averages each method's `score.py` file over the sequences and writes
`comparison_summary.json` beside them. It refuses files made over different sequences, so use
a data root that holds only the set you want in the table. That set, with its seeds, counts and
size, goes into the paper's `results/` with the commit and the command that wrote it, as that
folder's README asks.

## The test set

The paper's comparison runs on one fixed set of 120 sequences, of 24 frames at 1024 pixels,
half of them plain and half with a hard edge in focus, that `balanced_test_set.py` writes into
one data root. Every sequence is kept or passed over by a rule; none was chosen by looking
at it.

```bash
cd backend && uv run --extra render --extra library python ../comparison/balanced_test_set.py \
  --output data/balanced_test_set
cd .. && comparison/run_all.sh backend/data/balanced_test_set
for sub in plain hard hair fire smoke fine; do
  for m in drbokeh mpib_rt bokehme bokehme_classical any_to_bokeh; do
    comparison/envs/render/bin/python comparison/score.py \
      --data-root backend/data/balanced_test_set/$sub --method $m
  done
  comparison/envs/render/bin/python comparison/summary.py \
    --data-root backend/data/balanced_test_set/$sub
done
```

- Every sequence has one or two objects, so that a box on an object's edge shows one
  transition, between the object and what lies behind it.
- `plain-01` to `plain-60` are the first 60 seeds from 4,000,000 that can be placed and whose
  background has detail, with any object of the library. On a flat background, such as a
  white wall, no renderer's blur shows; `test_set.py` says how detail is measured.
- `hair-01` to `hair-15`, and 15 each of `fire`, `smoke` and `fine` (fine detail), focus on
  one of 107 library objects that `hard_edge_objects.txt` lists with their category, picked
  by hand for their edges. A light edge, and every flame and wisp of smoke, goes on a dark
  background, of mean luminance below 0.25; a dark edge on a light one, above 0.65.
- Each category takes seeds from its own start, and keeps one when the edge of the object in
  focus has a luminance contrast of 0.15 or more against what lies behind it and the object
  shows on 1 % of the frame or more. No object is in focus more than twice. The docstring of
  `balanced_test_set.py` gives the measures.
- `selection.csv` gives each sequence's group, category, seed, objects, the object in focus,
  its background, and the contrast and share it was kept for.
- `plain/`, `hard/`, `hair/`, `fire/`, `smoke/` and `fine/` beside `sequences/` are data roots
  that link to their own sequences. The loop above scores each method there, and `summary.py`
  gives each subset its own table; the renders are already in place.

`test_set.py` writes the earlier set of 40, which the comparison ran on until 2026-10-19:
`any-01` to `any-32`, the first 32 seeds from 1,000,000 whose background has detail, and
`night-01` to `night-08`, eight night scenes with small lights, each a different background,
which `night/` links to.

## Looking at the results

`review.py` lays a compared test set out for looking at, one folder per sequence:

```bash
comparison/envs/render/bin/python comparison/review.py collect \
  --data-root backend/data/test_set --out backend/data/test_set_review --link --every-frame
comparison/envs/render/bin/python comparison/review.py sheets backend/data/test_set_review
```

- `<sequence>/<method>/<frame>.png` holds each method's frames, with the same file names in
  every method's folder, so that a viewer such as VPV can flip between them. The methods are
  `all_in_focus`, `ours`, `drbokeh`, `mpib`, `bokehme` and `any_to_bokeh`.
- `<sequence>/boxes.json` lists candidate sheets: three frames where Dr.Bokeh, MPIB and
  BokehMe part most from ours at the edge of the object in focus, each with two pairs of
  boxes. A box is 96 to 240 pixels a side, so the enlargements show the edge at different
  magnifications; the docstring of `review.py` gives the score that places them.
- `<sequence>/sheets/<frame>-<a|b>.png` draws each candidate as Dr.Bokeh's Fig. 1 does: the
  frames side by side, two boxes on each, the boxed regions enlarged beneath.
- `sheets` draws them again from `boxes.json`, so a box can be moved by editing it.
  `--outline` sets the white along the colored lines, `--name` another folder for a trial,
  and `--kept` only the sheets left in `sheets/` after the unwanted ones are deleted.
- Without `--every-frame`, only the candidates' frames are copied, for a folder to take
  elsewhere; `--link` links the frames instead of copying them.

## Adding a method

Add a function to `setup.sh` that clones the pinned commit and builds what the method needs,
and a `run_<method>.py` that writes `bokeh_<method>/` in our layout, with `common.py` doing the
reading of our sequences. The method's name then works with `score.py` unchanged. A method
that takes one frame and a disparity map, as BokehMe and the full MPIB pipeline do, reads
`all_in_focus/` and `disparity/` instead of the layers.
