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
`K|d - zf| + 1`, so an in-focus pixel still spreads a small disk. `score.py` writes `comparison_drbokeh.json` with, per frame, the PSNR and the mean absolute
difference over the whole frame and over a band around the object edges, where a layered and a
single-layer renderer part.

The edge band is the square of 16 pixels around every edge of every object's alpha mask.

## Adding a method

Add a function to `setup.sh` that clones the pinned commit and builds what the method needs,
a `run_<method>.py` that writes `bokeh_<method>/` in our layout, and the method's name works
with `score.py` unchanged. A method that takes one frame and a disparity map, as BokehMe and
the full MPIB pipeline do, reads `all_in_focus/` and `disparity/` instead of the layers.
