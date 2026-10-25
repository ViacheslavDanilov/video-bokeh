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
removed. A survey of each candidate method's inputs, licenses and difficulty is among the
author's local notes.

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

`--composite gamma` writes `bokeh_drbokeh_cg/` instead, Dr.Bokeh composited as ours is. Each
layer is still scattered by Dr.Bokeh's own kernel in linear light; its straight color then
returns to gamma values on its own, and the layers are composited there with Dr.Bokeh's
occupancy. The same composite, left in linear light (`power` 1 in `common.py`), reproduces
`bokeh_drbokeh/` exactly. The published composite, `bokeh_drbokeh/`, stays Dr.Bokeh's row in
the comparison; the other shows how much of the difference from ours is the compositing space.

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

Each ray composites the layers it meets, and the kernel averages the rays of a pixel. As
published, both happen in linear light. Our frames, Stage B's `all_in_focus/` and our bokeh,
composite the layers in gamma values, and on a soft in-focus edge, such as hair or smoke, the
two composites differ before any blur does. So the comparison's reference is MPIB composited in
gamma values:

```bash
comparison/envs/render/bin/python comparison/run_mpib_rt.py --data-root backend/data/cmp \
  --composite gamma
```

It writes `bokeh_mpib_rt_cg/`. `mpib_kernel.py` edits MPIB's kernel so that each ray
composites the layers in gamma values and its color is raised to 2.2 before the rays are
averaged, so that the blur stays in linear light. Where every layer that a pixel's rays meet
lies at the focus plane, the rays land on the same pixels and the result is Stage B's
composite. Elsewhere the rays spread, over a defocused background behind hair in focus or
across the fringe of a defocused occluder, and still mix in linear light there, where ours
composites the blurred alpha in gamma values. Given
linear colors and the power 1, the edited kernel reproduces `bokeh_mpib_rt/` to within one gray
level, on 0.0023 % of the values of a 24-frame sequence, from the order of the sums.

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

## Our renderer on one frame

The ablation that separates the layers from the renderer: our own renderer, with the
all-in-focus frame as its only layer and the composite disparity as that layer's disparity.
The renderer's disk kernel, radius binning and gamma are its defaults, and the strength and
focus are the ones that rendered `bokeh/`. What separates the result from `bokeh/` is what
flattening the layers loses: the background an object hides, the alpha mattes, and each layer's
own disparity at a soft edge, where the composite disparity is blended by alpha. The 8-bit color
and the 16-bit disparity the frame is written at add a little more. Nothing to set up beyond
the render environment.

```bash
VIDEO_BOKEH_LAYERED_DEVICE=cuda comparison/envs/render/bin/python \
  comparison/run_ours_one_frame.py --data-root backend/data/cmp
comparison/envs/render/bin/python comparison/score.py --data-root backend/data/cmp --method ours_one_frame
```

It writes `bokeh_ours_one_frame/`. `run_all.sh` runs and scores it with the others.

## Any-to-Bokeh

[Any-to-Bokeh](https://github.com/vivoCameraResearch/any-to-bokeh) (ICLR 2026; code and
weights CC BY-NC 4.0) is a video diffusion model, which this pipeline once carried as a bokeh
renderer. It is the learned baseline of the comparison, not a reference. It needs an
environment of its own, Python 3.10 with the `diffusers` and `transformers` versions
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
Dr.Bokeh and MPIB in both compositing spaces, scores each against our bokeh and against MPIB
composited in gamma values, and prints a table of each:

```bash
comparison/run_all.sh backend/data/cmp
```

The sequences must hold their layers and our bokeh, so that every method gets the focus and
the strength that our renderer recorded. The command stops before it starts if a method is not
set up. `summary.py` averages each method's `score.py` file over the sequences and writes
`comparison_summary.json` beside them. It refuses files made over different sequences, so use
a data root that holds only the set you want in the table. The scores against MPIB go into
`vs_mpib/` inside the data root, a data root of links to the same sequences, with a summary of
their own. Ours against MPIB is the `mpib_rt_cg` row against ours, as both scores are
symmetric. The set, with its seeds, counts and size, goes into the paper's `results/` with the
commit and the command that wrote it, as that folder's README asks.

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
  for m in drbokeh mpib_rt bokehme bokehme_classical ours_one_frame any_to_bokeh; do
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
  shows on 1 % of the frame or more. No object is in focus in more than two kept sequences,
  or in more than three passed over. The docstring of `balanced_test_set.py` gives the
  measures.
- `selection.csv` gives each sequence's group, category, seed, number of objects and their
  ids, the object in focus, its background and that background's side, dark or light, and
  the contrast and share it was kept for.
- `plain/`, `hard/`, `hair/`, `fire/`, `smoke/` and `fine/` beside `sequences/` are data roots
  that link to their own sequences. The loop above scores each method there, and `summary.py`
  gives each subset its own table; the renders are already in place.

`test_set.py` writes the earlier set of 40, which the comparison first ran on:
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
  `all_in_focus`, `ours`, `drbokeh`, `mpib`, `bokehme` and `any_to_bokeh`. `mpib` is the
  comparison's reference, MPIB's ray tracer composited in gamma values (`bokeh_mpib_rt_cg/`),
  both in the sheets, labeled "MPIB", and in the placing of the boxes. A sequence that has only
  the linear composite, `bokeh_mpib_rt/`, as a data root made before that reference did, shows
  that instead.
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

## Speed

`bench_speed.py` times each method's render per frame, on the card or on the CPU. It calls
the adapters' own functions, so each method renders what it renders for the comparison. The
models are loaded, every frame is read and prepared in memory, and its inputs are on the
device before the clock starts; a synchronize on either side of the render call makes the
time the card's. Every frame of a sequence is rendered once and discarded before the frames
are timed, so that the timed pass meets no first-use cost, such as an FFT or cuDNN plan for
a size not seen before. `--warmup` sets a number of frames instead.

```bash
# On the card, the process kept to the eight performance cores of the lab's CPU
taskset -c 0-7 comparison/envs/render/bin/python comparison/bench_speed.py run \
  --method drbokeh --device cuda --threads 8 --data-root backend/data/cmp --size 2048 \
  --output speed.jsonl
# On the CPU, the same eight cores and threads
OMP_NUM_THREADS=8 taskset -c 0-7 comparison/envs/render/bin/python \
  comparison/bench_speed.py run --method ours --device cpu --threads 8 \
  --data-root backend/data/cmp --size 2048 --output speed.jsonl
comparison/envs/render/bin/python comparison/bench_speed.py summary speed.jsonl --out-dir .
comparison/envs/render/bin/python comparison/bench_speed.py env > speed-environment.json
```

What the clock holds differs by method, as each takes its inputs in a different form:

| Method | Timed | Not timed |
|---|---|---|
| `ours`, `ours_one_frame` | `render_bokeh`: colors to linear light and back, the radii, the spread of the radius around each object, the binning, the disks, the FFTs and the composite | reading, resampling, stacking the layers, copies to and from the device |
| `drbokeh` | `Multi_Layer_Renderer.forward`: the focus subtracted, each layer scattered, the composite | the disparity extended past each alpha, the lens size and its kernels, colors to linear light and back |
| `mpib_rt`, `mpib_rt_cg` | `ModuleRenderRT.forward`: the aperture's sample grid, the kernel's source filled in, the CuPy kernel | the plane fit, colors to linear light and back, NaN set to 0 |
| `bokehme` | the demo's `pipeline` whole: colors to linear light and back, the scatter, ARNet, IUNet at each scale and the blend | the defocus map |
| `bokehme_classical` | the pipeline's first lines: colors to linear light and back, and the scatter | the defocus map |
| `any_to_bokeh` | the pipeline call: the VAE encoder, the image encoder, the UNet's one step, the VAE decoder and the frames converted to images, which copies them off the card | the data loader, which reads the frames, resizes them to 1024 x 576 and computes the circles of confusion; copies to the card; the video written |

- The methods are `ours`, `ours_one_frame`, `drbokeh`, `mpib_rt`, `mpib_rt_cg`, `bokehme`,
  `bokehme_classical` and `any_to_bokeh`. Only our renderer also runs on the CPU. MPIB's ray
  tracer and BokehMe's scatter are CuPy kernels whose CPU branch raises an error, Dr.Bokeh's
  CPU scatter is a Python loop over every pixel and every kernel tap, and Any-to-Bokeh's demo
  runs on `cuda:0` in float16.
- `--size` resamples every stream by nearest neighbor before the render, in the memory
  layout it has at its own size, so a sequence written at 1024 pixels is timed at 512 or 2048
  with the same content. Stage B cannot write that content at another size from a library
  built at 1024: it places a background by its pixels, so a 1536-pixel background covers only
  the middle of a 2048-pixel frame.
- Any-to-Bokeh renders at 1024 x 576 whatever size it is given, so it takes no `--size`. Its
  demo groups a sequence's frames eight at a time, four overlapping, and renders two groups
  per call of its pipeline, a last group alone. `bench_a2b.py` times each call under the
  model's own environment, and each frame a call returns takes the call's time over its frame
  count. Unlike `a2b_launch.py`, it keeps the UNet on the card while the VAE decodes, as 24
  frames fit, and leaves TF32 at torch's default, as the demo runs it.
- `--threads` sets torch's CPU threads. On a CPU with performance and efficiency cores, keep
  the process to one kind with `taskset`: on the lab's, torch's default of 24 threads over
  every core left single frames many times their sequence's median. Each record names its
  threads, the CPUs the process could use and `OMP_NUM_THREADS`.
- The run waits until no other process holds memory on the card. Each sequence appends a
  JSON line with every frame's time; the peak memory that torch allocated on the card, which
  leaves out CuPy's own and the CUDA context; the card's clock and temperature after the
  timed frames; and, where the sequence holds the method's frames from the comparison, how far
  the first timed frame is from them, in 8-bit levels.
- `summary` writes `method-speed-sequences.csv`, one row per method, device, size and
  sequence, with the sequence's object count, and `method-speed.csv`, the mean, median and
  quartiles over every timed frame of each method, device and size.

## Adding a method

Add a function to `setup.sh` that clones the pinned commit and builds what the method needs,
and a `run_<method>.py` that writes `bokeh_<method>/` in our layout, with `common.py` doing the
reading of our sequences. The method's name then works with `score.py` unchanged. A method
that takes one frame and a disparity map, as BokehMe and the full MPIB pipeline do, reads
`all_in_focus/` and `disparity/` instead of the layers.
