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
| `--subject-thr` | float | `0.5` | minimum CLIP subject score to keep a foreground |

### Depth estimators

Every model returns disparity, near larger than far, so a library built with any of them works
the same in Stage B. The library records the `--model` string in each foreground's metadata.

| `--model` | checkpoint | weights license |
|---|---|---|
| `da2-small` | `depth-anything/Depth-Anything-V2-Small-hf` | Apache-2.0 |
| `da2-base` | `depth-anything/Depth-Anything-V2-Base-hf` | CC BY-NC 4.0 |
| `da2-large` | `depth-anything/Depth-Anything-V2-Large-hf` | CC BY-NC 4.0 |
| `depth-pro` | `apple/DepthPro-hf` | research only |
| `da3-mono-large` | `depth-anything/DA3MONO-LARGE` | Apache-2.0 |
| `da3-metric-large` | `depth-anything/DA3METRIC-LARGE` | Apache-2.0 |

Licenses as checked on 2026-09-30, and on 2026-10-01 for `da3-metric-large`. Non-commercial
weights are fine for a research dataset. Both `da3-*` need an environment of their own first, as
the next section says. `da3-metric-large` has not run yet; the lab machine runs it first.

The `da2-*` and `depth-pro` run in this process, in the environment the `library` extra
installs, under every runner: they need no environment of their own.

They could once also run in Docker images of their own at `uv.lock`'s versions. On the
RTX 5090 the libraries those built took 61 s for `da2-small` and 89 s for `depth-pro`.
Against the in-process libraries, Depth Pro's 60 depth maps were identical and `da2-small`'s
at most 0.002% of the range apart, so the images added nothing and were dropped.

**Depth Anything 3's other checkpoints are left out on purpose.** Small, Base and Large are
multi-view models, which estimate depth from several views of one scene at once. Their output
has no sky estimate, so the package never sets a sky to the far end, and where a sky lands is
up to the image. Small and Base, run on 20 of the dev backgrounds, agreed with `da2-large` at
medians of 0.75 and 0.81, but on `testval__h_7b2a0862`, a background with sky, at 0.10 and
0.02, where `da3-mono-large` holds 0.96. A dataset cannot leave its skies to the image. Large
1.0 and Giant are CC BY-NC 4.0 besides.

### Depth Anything 3's own environment

No `da3-*` estimator can run in the backend environment: Depth Anything 3 pins `numpy<2`, its
Python range stops before 3.13.1, and it depends on `xformers`, which has no macOS wheel. It runs
in a Python 3.12 venv of its own instead, as a worker process that Stage A starts and talks to.
Build that venv once:

```bash
scripts/setup_depth_anything_3.sh
```

Run it from the repository root. It puts the venv at `backend/envs/depth-anything-3/.venv`,
which git ignores. It leaves out `xformers`, which inference does not need, and `pycolmap`,
whose own OpenMP runtime clashes with torch's. To use a venv somewhere else, set
`VIDEO_BOKEH_DA3_PYTHON` to its interpreter. Without either, a `--model da3-*` stops before any
asset is processed and names the script.

`VIDEO_BOKEH_RUNNER=docker` runs the worker in the `video-bokeh-da3` image instead, which
`make images` builds with the same packages; nothing else changes. On the RTX 5090 a
Mono-Large library from the dev pools took 56 s that way, and its depth maps matched the venv's
to 0.003% of the range on average over 47 assets, 0.12% at the worst pixel.

Mono-Large's weights, 1.34 GB, download on first use, and Metric-Large's are the same size.
After that, Mono-Large took 8.2 s for 3 foregrounds and 1 background at size 512 on an Apple
M3 Pro.

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
   the `da3-*` estimators need anything: their own venv. The reason is printed under the table.
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
Without `--model`, `--measure` loads every registered estimator and so downloads whatever is not
cached: 5.97 GiB of checkpoints from scratch, by the Hub's metadata on 2026-10-01. On a machine
short of disk or memory, name the ones to measure.

Measured on an Apple M3 Pro:

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

## `video_bokeh.library.split` — draw the test foregrounds

Draws the foregrounds of the test split and writes their ids, sorted, one per line, to
`backend/src/video_bokeh/core/test_foregrounds.txt`. It takes `--fraction` of each subject that
CLIP gave the library's foregrounds, so each subject is in the test split in its own share.
Backgrounds need no draw, because they follow BG-20k's split
([dataset-layout](dataset-layout.md#the-train-and-test-splits)).

**The list is tracked, and it was drawn once from the published library.** Drawing it again,
with other flags or from another library, changes the benchmark and the scene every seed names.

```bash
uv run python -m video_bokeh.library.split --library-root data/library/da2-large \
  --predictions data/magick/predictions.csv
```

| flag | type | default | meaning |
|---|---|---|---|
| `--library-root` | path | **required** | the library whose foregrounds are drawn from |
| `--predictions` | path | **required** | the CLIP predictions of its MAGICK pool, as `acquire.classify` writes them; the draw reads `top_subject` |
| `--fraction` | float | `0.1` | the share of each subject drawn, rounded per subject |
| `--seed` | int | `0` | seeds the draw, with the subject |
| `--output` | path | the tracked list | where the ids are written |

## `video_bokeh.library.hub` — publish or download a library

`pack` writes a library into tar shards of about 2 GB under `library/`, with
`library/index.json`, a dataset card `README.md`, the card's figure `assets/preview.jpg` and
its video `assets/preview.mp4`, for a Hugging Face dataset repository. The library sits under
`library/` so that the generated sequences can sit beside it in the same repository. The
shards hold only what Stage B reads: each foreground's `rgb.png`, `alpha.png`, `depth.png` and
`meta.json`, and each background's `rgb.png` and `depth.png`. A shard holds whole items, in
WebDataset's layout: an item's files share its id, as `<id>.rgb.png`, `<id>.alpha.png`,
`<id>.depth.png` and `<id>.json`. Each item also carries `<id>.depth_preview.jpg`, its
disparity in color at the item's size, which the Hub's viewer shows and nothing reads. The
card declares a `foregrounds` and a `backgrounds` subset, so the viewer and the `datasets`
library read an item as one row. `fetch` downloads such a repository and unpacks it into a
library root that Stage B and the sequence stream take as they are, as
`foregrounds/<id>/rgb.png` and so on without the previews, one shard at a time, so the disk
holds the library and one shard at most. Run again, `fetch` downloads only the shards it has
not unpacked yet. `fetch` needs `huggingface-hub`, which the `loader` and `library` extras
install, and so does `hf upload-large-folder`. The card names Depth Anything V2 Large, so
`pack` takes only a library built with it.

- **The card's text is `backend/src/video_bokeh/library/hub_card.md`.** Edit it there. `pack`
  fills in each `$name` from the index: counts, image sizes, shards and gigabytes.
- **The figure shows the library, and the video what Stage B makes of it.** The figure holds
  four foregrounds and three backgrounds on tinted cards under two headed sections, a JPEG
  about 2,500 pixels wide and 3 MB at most. The video plays three sequences of 96 frames at
  1024 pixels in the demo's six panes, all in focus, disparity, mattes, bokeh, optical flow
  and occlusion, as H.264 at 24 frames per second. Rendering the sequences at that size
  needs about 45 GB of memory. `pack` spreads the items evenly over the sorted ids and takes
  seeds 0, 1 and 2. The video needs torch and imageio's
  ffmpeg, which the `library` extra installs; `--no-preview` leaves both out.
- **`preview` draws both again in a packed folder, and its card,** of the items and seeds it
  is given, so a better example costs no packing. A seed whose objects cannot be placed is
  refused. Stage again afterwards into an empty folder, so the staged card shows them too.
- **`stage` uploads a library in parts.** It hard-links every `--every`-th shard of each kind,
  the full index, the figure and the video into a folder of its own, with a card that says
  how many shards and items are online. A folder packed before the video needs `preview`
  first. The shards it takes are spread over the sorted ids, so a part
  draws from the whole sorted list; with `--every 5` it holds both BG-20k splits. Its output
  must be on the same disk as the packed folder.
  Uploading the packed folder afterwards adds the rest and the card of the whole library.
  Each upload sends the shards first and the card last, so a card never goes live before
  the shards it describes.

```bash
uv run python -m video_bokeh.library.hub pack --library-root data/library/da2-large \
  --output data/library-packed
uv run python -m video_bokeh.library.hub preview --library-root data/library/da2-large \
  --packed data/library-packed --foregrounds 6M__6MV7SSxmwd 0S__0SUuLNXyEz 3n__3nqLIHRgfa \
  1b__1bGRKnW1f3 --backgrounds train__h_a415d5e8 train__h_a7671d5b testval__h_ea29ed84 \
  --seeds 1005 1033 1050
uv run python -m video_bokeh.library.hub stage --packed data/library-packed \
  --output data/library-staged --every 5
hf upload-large-folder vdanilov/video-bokeh data/library-staged --repo-type dataset \
  --exclude README.md
hf upload vdanilov/video-bokeh data/library-staged/README.md README.md --repo-type dataset
hf upload-large-folder vdanilov/video-bokeh data/library-packed --repo-type dataset \
  --exclude README.md
hf upload vdanilov/video-bokeh data/library-packed/README.md README.md --repo-type dataset
uv run python -m video_bokeh.library.hub fetch --repo vdanilov/video-bokeh \
  --output data/library/da2-large
```

| command | flag | default | meaning |
|---|---|---|---|
| `pack` | `--library-root` | **required** | the library to publish |
| `pack` | `--output` | **required** | where the shards, index, card and figure go |
| `pack` | `--shard-gb` | `2` | a shard closes once it holds this many gigabytes |
| `pack` | `--repo` | `vdanilov/video-bokeh` | the repository the card's commands name |
| `pack` | `--no-preview` | off | draw no figure or video, and show neither in the card |
| `preview` | `--library-root` | **required** | the library the packed folder holds |
| `preview` | `--packed` | **required** | a folder `pack` wrote |
| `preview` | `--repo` | `vdanilov/video-bokeh` | the repository the card's commands name |
| `preview` | `--foregrounds` | spread evenly | up to four foreground ids for the figure |
| `preview` | `--backgrounds` | spread evenly | up to three background ids for the figure |
| `preview` | `--seeds` | `0 1 2` | the sequences the video plays |
| `stage` | `--packed` | **required** | a folder `pack` wrote |
| `stage` | `--output` | **required** | the folder to upload first |
| `stage` | `--every` | **required** | stage shards 0, n, 2n, … of each kind; `1` stages all |
| `stage` | `--repo` | `vdanilov/video-bokeh` | the repository the card's commands name |
| `fetch` | `--repo` | **required** | a Hugging Face dataset repository of shards |
| `fetch` | `--output` | **required** | the library root to write |
| `fetch` | `--revision` | latest | a branch, tag or commit of the repository |

## `video_bokeh.scenes.generate` — Stage B

Samples scenes from the library and writes the sequence tree in [dataset-layout](dataset-layout.md).
Each run also rewrites `manifest.csv` (including the background asset id), `objects.csv`
(each object's trajectory endpoints and fallback flag), and `run.json` (flags, library,
estimator, versions, bokeh device, counts, skipped seeds and elapsed time).
The writer removes any old manifest before writing sequences. It writes `objects.csv`
and `run.json` first, then writes `manifest.csv` atomically as the run's completion marker.

| flag | type | default | meaning |
|---|---|---|---|
| `--library-root` | path | **required** | library built by Stage A |
| `--output` | path | **required** | dataset root to write |
| `--count` | int | `10` | sequences to attempt |
| `--frames` | int | `80` | frames per sequence |
| `--size` | int | `1024` | square frame side |
| `--seed` | int | `0` | sequence `i` is seeded from `seed + i` |
| `--n-objects-min` | int | `1` | fewest objects in a scene |
| `--n-objects-max` | int | `5` | most objects in a scene. No format ceiling; the depth axis binds around 5 — see [dataset-layout](dataset-layout.md) |
| `--split` | `train`, `test` or `all` | `train` | the assets the scenes draw from: `train`, the ones training sees, `test`, the benchmark's, or `all`, as every run before the split did — see [dataset-layout](dataset-layout.md#the-train-and-test-splits) |
| `--layers` | flag | off | also write `layers/`, what each frame was composited from, for a layer-wise bokeh renderer — see [dataset-layout](dataset-layout.md) |
| `--flow` | flag | off | also write `flow/`, each frame's exact forward optical flow to the next, as KITTI's 16-bit PNG — see [dataset-layout](dataset-layout.md) |
| `--flow-back` | flag | off | also write `flow_back/`, each frame's exact backward optical flow to the previous, in the same format |
| `--occlusion` | flag | off | also write `occlusion/`, for each frame but the last an 8-bit mask of the pixels whose surface the next frame does not show — see [dataset-layout](dataset-layout.md) |
| `--bokeh` | flag | off | also render each sequence's `bokeh/` in the same run, with the layered renderer, from the layers in memory; needs torch |
| `--bokeh-strength` | float | `16` | the bokeh's strength: the blur radius in pixels, at a 1024-pixel width, one unit of disparity from the focus |

`bg_band_top` is not exposed on the CLI. Changing it needs the Python API.

## `video_bokeh.scenes.stats` — dataset statistics

Reads the current run's records and manifest-listed sequence files, without resampling.
Prints JSON with counts, object-count distribution, depth motion and fallback shares,
rejections, asset reuse, first-frame active band widths, object focus share, bytes per stream
and per frame, and the original run record. Formats and denominators are in
[dataset-layout](dataset-layout.md#dataset-statistics).

```bash
uv run python -m video_bokeh.scenes.stats --data-root data/synth_dev --output stats.json
```

| flag | type | default | meaning |
|---|---|---|---|
| `--data-root` | path | **required** | dataset root containing `manifest.csv`, `objects.csv` and `run.json` |
| `--output` | path | unset | save the printed JSON to this file |

Datasets without `objects.csv` or `run.json` produce a usage error naming the missing file.

## `video_bokeh.render.run` — render bokeh again

Renders the bokeh again for written sequences, and writes each one's `bokeh/` stream, as
[dataset-layout](dataset-layout.md) describes. The layered renderer needs their layers. It
is optional, since Stage B renders the bokeh in its own pass with `scenes.generate --bokeh`,
and it needs the `render` extra. The layered renderer is the default, and
[generate-a-dataset](../how-to/generate-a-dataset.md) has its command. Use it to render again,
at another strength or focus, what `scenes.generate --bokeh` rendered in the same run as the
frames.

| flag | type | default | meaning |
|---|---|---|---|
| `--data-root` | path | **required** | dataset root containing `sequences/` |
| `--seqs` | list | all | comma-separated sequence ids, e.g. `0001,0003` |
| `--renderer` | str | `layered` | a renderer below, or `package.module:ClassName` for your own |
| `--strength` | float | `16` | blur strength: the blur radius in pixels, at a 1024-pixel width, one unit of disparity from the focus |
| `--focus-disparity` | float | one object, drawn by area | one in-focus disparity in `[0, 1]` for every frame |
| `--focus-object` | int | one object, drawn by area | the object the focus follows, by its page in `alpha/`; every sequence rendered must show it alone in some frame |
| `--missing` | flag | off | render only the sequences without `bokeh/`, leaving out any the renderer cannot take |

With `--missing`, a sequence that already has `bokeh/`, or that has none of the layers
`layered` needs, is named and left out rather than handed over, where it would fail the whole
batch. A directory whose name starts with a dot is never a sequence: the API generates under
`.tmp-*` and renames.

| `--renderer` | runs in | setup |
|---|---|---|
| `layered` | this process, on the CPU, an NVIDIA card or a Mac's GPU | sequences written with `scenes.generate --layers` |

The focus follows one object by default, drawn by the area it holds alone, keyed on the
scene's seed, so `render.run` draws the object `scenes.generate --bokeh` would have. `--focus-object` names the object instead, followed by the same rule. `bokeh/focus.json` records
the object, each frame's in-focus disparity, the renderer and its strength.

**`layered` is the layer-wise renderer** that [layered-bokeh](../explanation/layered-bokeh.md)
explains. It reads `layers/`, `alpha/` and `disparity/` and writes `bokeh/` losslessly. It
refuses the whole batch, before rendering any, when a sequence has no complete `layers/`. It
runs on the CPU unless `VIDEO_BOKEH_LAYERED_DEVICE` is `cuda` or `mps`, and falls back to the
CPU when that device is not there. On the lab machine, an 80-frame sequence at 512 pixels
took 13 s on its 24 CPU cores and 6 s on the RTX 5090. At 1024 pixels it took 40 s and 20 s.
Most of the time on the GPU is reading the layers and writing the PNGs.

### Your own renderer

Pass `--renderer my_package.my_module:MyRenderer`. The tool creates the class with no arguments
and calls `render(self, sequence_dirs, strength, focus_disparity)` once, with every sequence,
adding `focus_object=` only when `--focus-object` is given; a renderer without that keyword
then fails.
It must write `<sequence>/bokeh/<frame>.png` for each one: RGB uint8, the sequence's own size,
named like the `all_in_focus` frames. The interface is
`video_bokeh.render.base.BokehRenderer`.

## `video_bokeh.preview.pack` — PNG streams to MP4

| flag | type | default | meaning |
|---|---|---|---|
| `--data-root` | path | **required** | dataset root containing `sequences/` |
| `--streams` | list | `all_in_focus` | which stream directories to encode |
| `--fps` | int | `24` | frame rate |
| `--quality` | int | `10` | 0–10, higher is better. CRF = `round(51 - 3.4 * quality)`, so 10 is CRF 17 |
| `--seqs` | list | all | comma-separated sequence ids |
| `--colormap` | str | `spectral_r` | `spectral_r`, `grey` |

Videos use H.264 High with `yuv420p` pixels. Quality 10 uses lossy CRF 17, and
`ffprobe` confirms the High profile. The old default, imageio quality 10, meant
lossless H.264 at CRF 0, which uses the High 4:4:4 Predictive profile even with
`yuv420p`. Firefox's decoders refuse that profile on Windows and macOS, as Mozilla's
[`dom/media/platforms/PDMFactory.cpp`](https://raw.githubusercontent.com/mozilla-firefox/firefox/main/dom/media/platforms/PDMFactory.cpp)
specifies. Firefox playback was not tested here.

On an Apple M3 Pro, one 80-frame, 512 × 512 sequence from `da2-large` with one object
gave the results below. Encoding times include frame loading and preview coloring. Each
time is the median of three runs at 24 fps, using imageio's
FFmpeg 7.1 and libx264. PSNR (peak signal-to-noise ratio) compares decoded RGB with the
RGB frames passed to the encoder, over all pixels and frames. Higher is better.

| stream | old bytes | CRF 17 bytes | old seconds | CRF 17 seconds | old PSNR, dB | CRF 17 PSNR, dB |
|---|---:|---:|---:|---:|---:|---:|
| `all_in_focus` | 3,896,230 | 517,831 | 0.267 | 0.328 | 41.57 | 39.12 |
| `disparity` | 607,846 | 121,944 | 0.336 | 0.367 | 38.39 | 37.96 |
| `bokeh` | 3,450,942 | 485,625 | 0.265 | 0.295 | 41.90 | 39.57 |
| `flow` | 670,999 | 180,115 | 1.754 | 1.863 | 40.69 | 40.31 |
| `alpha` | 162,087 | 109,891 | 0.168 | 0.185 | 36.86 | 36.59 |

`ffprobe` reported High 4:4:4 Predictive before and High after for every stream, with
`yuv420p` pixels and 80 frames in each. CRF 0 was lossless only after conversion to
`yuv420p`, which discards color detail. That is why its RGB PSNR is finite. CRF 17
reduced file size at a small fidelity cost and took longer to encode in this run.

Disparity is a uint16 PNG, not RGB (see [dataset-layout](dataset-layout.md)), so it is packed
through `--colormap` rather than through the `Image.convert` path the other streams use.

Flow is KITTI's 16-bit PNG, one per frame but the last, so `--streams flow` colors it the
way optical-flow papers do: the hue is the direction, the saturation the speed, and white is
still. One scale, the fastest motion in the sequence, serves every frame. `--colormap` does
not apply. A still frame stands for the last frame, so the video is as long as the others.

`--streams flow_back` colors the backward flow the same way, with the still frame first,
since the first frame has no previous one. `--streams occlusion` packs the mask as stored,
white where the pixel is hidden in the next frame, with a black frame for the last.

The output name doesn't include the colormap, so re-running `--streams disparity` with a
different `--colormap` overwrites the previous `disparity.mp4` rather than writing a second file.

## `video_bokeh.loader.example` — a training loop on the sequence stream

Needs the `loader` extra.
[train-on-the-sequence-stream](../how-to/train-on-the-sequence-stream.md) runs it and reads its
source.

| flag | type | default | meaning |
|---|---|---|---|
| `--library-root` | path | `data/library_dev/da2-large` | library the stream draws its sequences from |
| `--steps` | int | `20` | training steps to run before it stops |

## `video_bokeh.loader.benchmark` — sequence-stream throughput

Needs the `loader` extra. Measures the protocol in [loader](loader.md#what-each-choice-costs),
prints one line per number, and optionally saves the flags, measurements and environment as JSON.
MiB per item counts all input tensors, including collated metadata. CUDA peak allocation
includes warm-up and timed rendering; CPU and MPS runs leave that JSON field null.

| flag | type | default | meaning |
|---|---|---|---|
| `--library-root` | path | **required** | library the stream draws its sequences from |
| `--streams` | list | `rgb,disparity,alpha,object_alphas` | comma-separated stream names |
| `--frames` | int | `24` | frames per item |
| `--size` | int | `512` | square frame side |
| `--objects-min` | int | `1` | fewest objects in a scene |
| `--objects-max` | int | `5` | most objects in a scene, also the tensor padding size |
| `--batch-size` | int | `4` | items per batch |
| `--workers` | int | `8` | DataLoader workers, with prefetch factor 2; 0 draws in this process |
| `--seed` | int | `0` | first sequence seed |
| `--gpu-bokeh` | flag | off | move every batch to the device and render with `batch_bokeh`; requires `layers`, `object_alphas` and `focus` |
| `--device` | `auto`, `cuda`, `mps`, `cpu` | `auto` | bokeh device; auto chooses CUDA, then MPS, then CPU; an unavailable explicit device is refused |
| `--bokeh-strength` | float | `16` | bokeh strength in the workers or on the device |
| `--min-timed-batches` | int | `15` | time at least this many batches, or twice the worker count if larger, after twice the worker count of warm-up batches (one with 0 workers) |
| `--output` | path | unset | JSON path for flags, measurements, torch version, resolved device and name, CPU count, UTC date and git commit (null if unavailable) |

## Acquisition

| module | flags |
|---|---|
| `video_bokeh.acquire.magick` | `--metadata` (csv), `--output`, `--count`, `--seed`, `--picked` |
| `video_bokeh.acquire.bg20k` | `--output`, and `--count`, `--seed` (default 11) to grow a pool one file at a time instead of downloading the archive. Needs no Kaggle account, and uses a token in `~/.kaggle/access_token`, or a legacy `~/.kaggle/kaggle.json`, when one exists |
| `video_bokeh.acquire.classify` | `--data-root`, `--output`, `--model`, `--pretrained`, `--device`, `--batch-size`, `--num-workers`, `--keep-existing` to classify only the images the output lacks, with the model that made the rest. Writes `predictions.json` beside the predictions, recording each run's rows, model, weights and date |

**The two sources carry licenses of their own**, as checked on 2026-10-22. MAGICK's images are
CC BY-NC 4.0, as its [project page](https://ryanndagreat.github.io/MAGICK/) states; its Hugging
Face card states none. BG-20k is MIT-licensed under its
[release agreement](https://jizhizili.github.io/files/gfm_datasets_agreements/BG-20k_Dataset_Release_Agreement.pdf),
which requires papers that use it to cite Li et al., "Bridging Composite and Real: Towards
End-to-end Deep Image Matting", IJCV 2021, and leaves each image's copyright with its owner.
A dataset built from them inherits MAGICK's non-commercial term, whichever estimator in
[Depth estimators](#depth-estimators) Stage A runs.

MAGICK writes `images/<first-two-characters>/<page_id>.png` and `metadata.csv` under
`--output`. Existing metadata rows keep their order, and new downloads follow in sample
order. HTTP 429 and 5xx responses get up to seven attempts, honoring `Retry-After` or
backing off from 5 to 60 seconds.

BG-20k writes `images/<split>/<file>` and `metadata.csv` (`filename,split`) in both modes.
Whole mode reuses a completed archive download and removes its copy after building the
pool. See [Full pools](../how-to/generate-a-dataset.md#full-pools) for the commands.

---

## Related

- [dataset-layout](dataset-layout.md) — what these commands write
- [generate-a-dataset](../how-to/generate-a-dataset.md) — the recipes that use them
