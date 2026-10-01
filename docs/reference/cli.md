---
type: reference
status: active
tags: [reference, cli, flags]
related: [dataset-layout, generate-a-dataset]
---

# CLI reference

Every flag of every `video_bokeh.*` module, read out of the `argparse` parsers. Defaults here are
the parser's defaults, not what a recipe happens to pass.

All commands run from `backend/` and go through `uv run`, so they use the locked environment:

```bash
uv run python -m video_bokeh.<role>.<module> [flags]
```

---

## `video_bokeh.library.build` — Stage A

Estimates depth once per asset and writes the artifact library.

| flag | type | default | meaning |
|---|---|---|---|
| `--fg-data-root` | path | **required** | MAGICK-style foreground pool |
| `--bg-data-root` | path | **required** | BG-20k-style background pool |
| `--output` | path | **required** | library root to write |
| `--size` | int | `1024` | square side for foreground assets |
| `--model` | str | `da2-large` | a model below, or `package.module:ClassName` for your own |
| `--device` | str | `auto` | `auto`, `cuda`, `mps`, `cpu` |
| `--neutral-bg-seed` | int | `0` | seed for the synthetic neutral backdrop |
| `--bg-margin` | float | `0.25` | oversize each background by this fraction per side, so Stage B's warp never shows its edge |
| `--nb-pixels-remove` | int | `5` | edge pixels trimmed before depth propagation |
| `--alpha-threshold` | float | `0.04` | alpha below this is treated as background |
| `--low-pct` | float | `2.0` | drop trusted-core pixels below this percentile as depth holes; `0` turns the cleanup off |
| `--limit-fg` | int | all | cap on foregrounds processed |
| `--limit-bg` | int | all | cap on backgrounds processed |
| `--subjects` | list | `person, animal, plant, food, object` | CLIP subject classes kept |
| `--styles` | list | `photo, render` | CLIP style classes kept |
| `--subject-thr` | float | `0.5` | minimum CLIP score to keep an asset |

### Depth estimators

Every model returns disparity, near larger than far, so a library built with any of them works
the same in Stage B. The library records the `--model` string in each foreground's metadata.

| `--model` | checkpoint | weights licence |
|---|---|---|
| `da2-small` | `depth-anything/Depth-Anything-V2-Small-hf` | Apache-2.0 |
| `da2-base` | `depth-anything/Depth-Anything-V2-Base-hf` | CC BY-NC 4.0 |
| `da2-large` | `depth-anything/Depth-Anything-V2-Large-hf` | CC BY-NC 4.0 |
| `depth-pro` | `apple/DepthPro-hf` | research only |
| `da3-mono-large` | `depth-anything/DA3MONO-LARGE` | Apache-2.0 |

Licences as checked on 2026-09-30. Non-commercial weights are fine for a research dataset.
`da3-mono-large` needs an environment of its own first, as the next section says.

### Depth Anything 3's own environment

`da3-mono-large` cannot run in the backend environment: Depth Anything 3 pins `numpy<2`, its
Python range stops before 3.13.1, and it depends on `xformers`, which has no macOS wheel. It runs
in a Python 3.12 venv of its own instead, as a worker process that Stage A starts and talks to.
Build that venv once:

```bash
scripts/setup_depth_anything_3.sh
```

Run it from the repository root. It puts the venv at `backend/envs/depth-anything-3/.venv`,
which git ignores. It leaves out `xformers`, which inference does not need, and `pycolmap`,
whose own OpenMP runtime clashes with torch's. To use a venv somewhere else, set
`VIDEO_BOKEH_DA3_PYTHON` to its interpreter. Without either, `--model da3-mono-large` stops
before any asset is processed and names the script.

The weights, 1.34 GB, download on first use. After that, 3 foregrounds and 1 background at
size 512 took 8.2 s on an Apple M3 Pro.

### Your own model

Pass `--model my_package.my_module:MyEstimator`. The class needs no registration and no change
to this repository. Stage A creates it with no arguments, then calls two methods:

1. `load(self, device)` puts the weights on a `torch.device`. It is called once.
2. `infer(self, images)` takes a list of RGB `PIL.Image` and returns one float32 NumPy array per
   image, the image's own height and width, with near larger than far. Scale and offset do not
   matter. A model that predicts depth returns its reciprocal.

`my_package` has to be importable from the environment `uv run` uses. A missing module, a
missing class, or a class without `load` and `infer` stops the command before any weights
load. The interface is `video_bokeh.library.depth.base.DepthEstimator`.

Three optional parts let `video_bokeh.library.check`, below, say more about the class.
Without them it still checks the class, and reports what it cannot know as unknown:

- `hf_model_id`, a class attribute naming the Hugging Face checkpoint, or a local checkpoint
  directory, so it can count the weights.
- `environment_problem(cls)`, a class method that returns why the estimator cannot run here,
  or `None`.
- `peak_memory(self)`, for an estimator that keeps its weights in another process: the bytes
  that process has used on its device.

## `video_bokeh.library.check` — will it run here?

Asks, before a library build, whether each depth estimator can run on this machine. Needs
`--extra library`, like Stage A.

```bash
uv run --extra library python -m video_bokeh.library.check
uv run --extra library python -m video_bokeh.library.check --measure
```

| flag | type | default | meaning |
|---|---|---|---|
| `--model` | str, repeatable | every registered estimator | a `--model` name from the table above, or `package.module:ClassName` |
| `--device` | `auto`, `cuda`, `mps`, `cpu` | `auto` | the device to judge against, chosen the way Stage A chooses it |
| `--measure` | flag | off | run one image through each ready estimator and report what it took |

It prints the device first: what `--device` resolves to and its memory, VRAM on CUDA and
system memory on MPS and the CPU, which MPS shares. When the requested device is not there, the
check says so; Stage A would fall back to the CPU without a word. Then three things for each
estimator:

1. **Environment.** Whether what it needs beyond the `library` extra is in place. Only
   `da3-mono-large` needs anything: its own venv. The reason is printed under the table.
2. **Weights.** The parameter count times four bytes, because every built-in runs in float32.
   It is read from the header of the cached checkpoint, and from the Hub only when nothing is
   cached, so it works offline once the weights are downloaded. `not downloaded` means the
   first build will download them first.
3. **Verdict.** `ready`, `environment missing` or `weights exceed memory`, against the
   device's memory.

**`ready` is necessary, not sufficient.** Inference also needs memory for activations, the
intermediate results of a forward pass, and the check does not estimate them. `--measure` is how
to find out: it runs one warm-up and one timed 1024 px image through each ready estimator, each
in a fresh process. When the weights were not cached before the run, the load time is marked
`(download)`, because it includes fetching them. An estimator that fails, running out of memory
for instance, gets `failed` and the reason under the table; the others are still measured.

Measured on an Apple M3 Pro on 2026-10-01:

```
Device: mps, 36.0 GiB of system memory, shared with the CPU

depth estimator  environment  weights, float32  verdict  load   per image  memory
da2-base         in place     0.4 GiB, cached   ready    3.4 s  0.18 s     1.5 GiB
da2-large        in place     1.2 GiB, cached   ready    4.5 s  0.51 s     2.3 GiB
da2-small        in place     0.1 GiB, cached   ready    3.3 s  0.08 s     1.2 GiB
da3-mono-large   in place     1.2 GiB, cached   ready    5.2 s  0.37 s     2.1 GiB
depth-pro        in place     3.5 GiB, cached   ready    4.5 s  5.98 s     20.5 GiB
```

**Depth Pro's memory is six times its weights.** That gap is what the verdict cannot see.

**The memory column means a different thing on each device**, as well as each backend can say
it. CUDA keeps a true peak allocation. MPS keeps none, so this is what its driver still holds
after the run. On the CPU it is the peak resident set, the most RAM the process ever held, which
counts nothing an MPS tensor holds. `da3-mono-large` reports its worker process, which holds the
weights.

The command exits 1 when any estimator it checked is not `ready`, or failed to measure. A
`--model` that names no estimator is a usage error, before anything is checked.

## `video_bokeh.scenes.generate` — Stage B

Samples scenes from the library and writes the sequence tree in [[dataset-layout]].

| flag | type | default | meaning |
|---|---|---|---|
| `--library-root` | path | **required** | library built by Stage A |
| `--output` | path | **required** | dataset root to write |
| `--count` | int | `10` | sequences to attempt |
| `--frames` | int | `80` | frames per sequence |
| `--size` | int | `1024` | square frame side |
| `--seed` | int | `0` | sequence `i` is seeded from `seed + i` |
| `--n-objects-min` | int | `1` | fewest objects in a scene |
| `--n-objects-max` | int | `5` | most objects in a scene. No format ceiling; the depth axis binds around 5 — see [[dataset-layout]] |

`bg_band_top` is not exposed on the CLI. Changing it needs the Python API.

## `video_bokeh.render.run` — Stage C

Renders bokeh for written sequences and writes each one's `bokeh/` stream, as
[[dataset-layout]] describes. It needs the `render` extra, and [[run-any-to-bokeh-inference]]
has the command. It has not run to completion on a GPU yet.

| flag | type | default | meaning |
|---|---|---|---|
| `--data-root` | path | **required** | dataset root containing `sequences/` |
| `--seqs` | list | all | comma-separated sequence ids, e.g. `0001,0003` |
| `--renderer` | str | `any-to-bokeh` | a renderer below, or `package.module:ClassName` for your own |
| `--strength` | float | `16` | blur strength, any-to-bokeh's `k` |
| `--focus-disparity` | float | the renderer's choice | one in-focus disparity in `[0, 1]` for every frame |

| `--renderer` | runs in | setup |
|---|---|---|
| `any-to-bokeh` | its own Python 3.10 venv, NVIDIA only | `scripts/setup_third_party.sh` |

any-to-bokeh focuses on the objects by default: each frame's in-focus disparity is the mean
under the union of the object mattes. `VIDEO_BOKEH_A2B_ROOT` and `VIDEO_BOKEH_A2B_PYTHON` point
at another checkout or interpreter.

### Your own renderer

Pass `--renderer my_package.my_module:MyRenderer`. Stage C creates the class with no arguments
and calls `render(self, sequence_dirs, strength, focus_disparity)` once, with every sequence.
It must write `<sequence>/bokeh/<frame>.png` for each one: RGB uint8, the sequence's own size,
named like the `all_in_focus` frames. The interface is
`video_bokeh.render.base.BokehRenderer`.

## `video_bokeh.bridge.any_to_bokeh` — the inference bridge

| flag | type | default | meaning |
|---|---|---|---|
| `--data-root` | path | **required** | dataset root containing `sequences/` |
| `--a2b-root` | path | `third_party/any-to-bokeh` | vendored inference checkout |
| `--dataset-name` | str | basename of `--data-root` | name under `demo_dataset/` and `csv_file/` |
| `--k` | str | `16` | blur-strength column written to the CSV |
| `--seqs` | list | all | comma-separated sequence ids, e.g. `0001,0003` |
| `--focus-disparity` | float | unset | pin one focus in `[0, 1]` for every frame. Overrides `--focus` |
| `--focus` | str | `alpha` | `alpha` = mean disparity under the mask; `full` = whole frame |

## `video_bokeh.preview.pack` — PNG streams to MP4

| flag | type | default | meaning |
|---|---|---|---|
| `--data-root` | path | **required** | dataset root containing `sequences/` |
| `--streams` | list | `all_in_focus` | which stream directories to encode |
| `--fps` | int | `24` | frame rate |
| `--quality` | int | `10` | imageio quality, 10 is visually lossless |
| `--seqs` | list | all | comma-separated sequence ids |
| `--colormap` | str | `spectral_r` | `spectral_r`, `grey` |

Disparity is a uint16 PNG, not RGB (see [[dataset-layout]]), so it is packed through
`--colormap` rather than through the `Image.convert` path the other streams use.

The output name doesn't include the colormap, so re-running `--streams disparity` with a
different `--colormap` overwrites the previous `disparity.mp4` rather than writing a second file.

## Acquisition

| module | flags |
|---|---|
| `video_bokeh.acquire.magick` | `--metadata` (csv), `--output`, `--count`, `--seed`, `--picked` |
| `video_bokeh.acquire.bg20k` | `--output`. Needs `~/.kaggle/kaggle.json` |
| `video_bokeh.acquire.classify` | `--data-root`, `--output`, `--model`, `--pretrained`, `--device`, `--batch-size`, `--num-workers` |

---

## Related

- [[dataset-layout]] — what these commands write
- [[generate-a-dataset]] — the recipes that use them
