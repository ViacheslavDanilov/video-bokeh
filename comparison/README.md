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
removed. Why these methods, with their inputs, licenses and difficulty:
`docs/reports/2026-10-15-bokeh-renderer-survey.md`, which is local to the author's machine.

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
the frame's width. Both renders read the same colors through the same power of 2.2.
`score.py` writes `comparison_drbokeh.json` with, per frame, the PSNR and the mean absolute
difference over the whole frame and over a band around the object edges, where a layered and a
single-layer renderer part.

One 80-frame sequence at 1024 pixels, seed 10031, on the RTX 5090, 2026-10-15: Dr.Bokeh took
110 s including the read; against our bokeh the PSNR was 36.2 dB over the frame and 26.4 dB in
the 16-pixel edge band, and the mean absolute difference 1.2 and 4.5 gray levels.

## Adding a method

Add a function to `setup.sh` that clones the pinned commit and builds what the method needs,
a `run_<method>.py` that writes `bokeh_<method>/` in our layout, and the method's name works
with `score.py` unchanged. A method that takes one frame and a disparity map, as BokehMe and
the full MPIB pipeline do, reads `all_in_focus/` and `disparity/` instead of the layers.
