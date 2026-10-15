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

## Adding a method

Add a function to `setup.sh` that clones the pinned commit and builds what the method needs,
and a `run_<method>.py` that writes `bokeh_<method>/` in our layout, with `common.py` doing the
reading of our sequences. The method's name then works with `score.py` unchanged. A method
that takes one frame and a disparity map, as BokehMe and the full MPIB pipeline do, reads
`all_in_focus/` and `disparity/` instead of the layers.
