# Scripts

Copy-paste recipes for setting up, building, analyzing, and visualizing the synthetic dataset. Run every command from the repo root unless noted.

## First-time setup on a new machine

`setup_third_party.sh` initializes the `any-to-bokeh` submodule and provisions a dedicated Python 3.10 venv for it under `backend/third_party/any-to-bokeh/.venv`. Each third-party tool owns its own venv — no shared env, so no pin conflicts. CUDA-only — intended for the server.

```bash
scripts/setup_third_party.sh
```

What it does:

1. `git submodule update --init --recursive` to pull `backend/third_party/any-to-bokeh/`.
2. Creates the venv, installs PyTorch 2.7.1 with CUDA 12.8 wheels; 2.7 is the first release with kernels for Blackwell cards such as the RTX 5090 (`CUDA_INDEX_URL` overrides the index, but only `cu118`, `cu126` and `cu128` carry 2.7.1, and a Blackwell card needs `cu128`), then installs `any-to-bokeh/requirements.txt`.
3. Downloads the UNet + VAE checkpoints from Google Drive via `uvx gdown` into `backend/third_party/any-to-bokeh/checkpoints/{unet,vae}/`. This path matches `inference_demo.py`'s defaults and is gitignored by the a2b submodule. If `gdown` fails (Drive rate-limit, auth, or quota), the script prints a manual fallback URL.
4. Downloads the Stable Video Diffusion base model (`stabilityai/stable-video-diffusion-img2vid-xt`, 4.2 GiB of fp16 weights by the Hub's metadata) from Hugging Face into `$HF_HOME`. The a2b inference script loads it with `local_files_only=True`, so it **must** be cached before running inference. If you've gated the model, run `huggingface-cli login` before the setup script.

Override the Google Drive file ID with `A2B_CHECKPOINTS_FILE_ID=<id>` if a2b ever republishes the archive.

Activate the venv before running any-to-bokeh:

```bash
source backend/third_party/any-to-bokeh/.venv/bin/activate
```

`video_bokeh.render.run` uses this venv on its own. Activating it is only for running
any-to-bokeh's scripts by hand.

The main backend env (used by every command in the sections below) is separate — managed by `uv sync --extra library` from the repo root.

`setup_depth_anything_3.sh` builds the venv that `--model da3-mono-large` and `--model da3-metric-large` run in. Only those two need it. It is a Python 3.12 venv under `backend/envs/depth-anything-3/.venv`, and unlike `setup_third_party.sh` it runs on a Mac. The command, and what the script leaves out and why, are in `docs/reference/cli.md`, section "Depth Anything 3's own environment".

## Build a synthetic dataset

`build_dataset.py` runs Stages A and B of the pipeline in order and stops. Stage C, which
renders bokeh, is not part of it.

1. **Stage A** — estimate depth once per asset and write the artifact library. The slow one.
2. **Stage B** — sample scenes from that library and write sequences. Fast, and repeatable
   from the same library.

### Just run it

```bash
uv run python scripts/build_dataset.py
```

A fresh clone has everything this needs. `backend/data/magick_dev` (30 foregrounds) and
`backend/data/bg-20k_dev` (30 backgrounds) are tracked on purpose, so nothing is downloaded
except the depth model, which Hugging Face caches on first use.

Defaults write `backend/data/library_demo` and `backend/data/demo`: 4 sequences, 24 frames,
512 px, 1 to 5 objects, `da2-small`. **Measured end to end on an Apple M3 Pro: 16 s**, of
which Stage A is 11 s. The script then prints what it wrote and the `vpv` command to look at it.

### Run it again

Stage A is reused unless you ask for it back, because rebuilding the library is the expensive
part:

```bash
uv run python scripts/build_dataset.py --count 10 --frames 80
uv run python scripts/build_dataset.py --rebuild-library --model da2-large --size 1024
```

### Useful flags

| flag | default | what it does |
|---|---|---|
| `--count` | `4` | sequences to generate |
| `--frames` | `24` | frames per sequence |
| `--size` | `512` | square frame side, passed to both stages when the script builds the library. A reused library keeps its own size, which Stage B upscales or downscales |
| `--n-objects-min` / `--n-objects-max` | `1` / `5` | objects per scene. Past five the depth axis starts refusing scenes — see `docs/reference/dataset-layout.md` |
| `--model` | `da2-small` | a depth estimator from `docs/reference/cli.md`, or `package.module:ClassName` for your own. `da2-large` is slower and better |
| `--rebuild-library` | off | rerun Stage A |
| `--seed` | `0` | sequence `i` comes from `seed + i` |

For what lands on disk, read `docs/reference/dataset-layout.md`. For the stages one at a
time, `docs/how-to/generate-a-dataset.md`.

### Render bokeh after the pipeline finishes

`build_dataset.py` writes no `layers/`, so Stage C's default, the layered renderer, refuses its
output. For our bokeh, run Stage B with `--bokeh`, or with `--layers` and then Stage C, as
section 5 of `docs/how-to/generate-a-dataset.md` shows. any-to-bokeh, kept for comparison,
renders the output as it is, with `--renderer any-to-bokeh` on a machine with an NVIDIA card
after `setup_third_party.sh`: `docs/how-to/run-any-to-bokeh-inference.md`.

## Run everything on the lab machine

`lab_run.sh` is the lab-machine test in one command: the device check with every depth estimator
measured, one library per estimator from the dev pools, the same sequences from each, their
bokeh, and MP4s to look at. It writes one log to send back. The setup it needs and what it
does step by step are in `docs/how-to/run-on-the-lab-machine.md`.

```bash
scripts/lab_run.sh
```

## Measure any-to-bokeh inference

`measure_a2b.sh` generates one 80-frame sequence, converts it, runs inference and reports wall clock and seconds per frame next to the GPU that produced them. No arguments. CUDA-only — `inference_demo.py` is pinned to `cuda:0`, so this is a lab-machine script.

```bash
scripts/measure_a2b.sh
```

The full transcript lands in `backend/data/measurements/a2b-<timestamp>.log`. Send that file back — it carries the commands, the card and the timing together. Details in `docs/how-to/run-any-to-bokeh-inference.md`.

## Analyze the MAGICK CLIP filter distribution

Regenerates the keep-curve plots and `summary.json` sidecar into the output directory configured at the top of the script. Re-run after re-classifying or after editing the keep / exclude sets.

```bash
uv run python scripts/analyze_magick_distribution.py
```

## Visualize sequences with VPV

`vpv` opens an N-pane viewer with synchronized playback across the streams. Run from inside the dataset's `sequences/` directory unless noted.

### Inspect the rendered streams

Composite next to depth — the standard post-render sanity check. Quote the globs so `vpv` expands them itself:

```bash
cd backend/data/demo/sequences && vpv "*/all_in_focus/*.png" "*/disparity/*.png"
```

An object that grows on screen must get brighter in the disparity pane. Disparity is raw 16-bit greyscale on disk, so `vpv` shows it grey; the `Spectral_r` colouring lives in the packed MP4s and in the API's video endpoint.

**There is no alpha pane.** Alpha is a multi-page TIFF with one page per object, and `vpv` renders only a TIFF's first page, so it would show object 0 and silently hide the rest. Read alpha with `video_bokeh.core._streams.read_alpha_tiff` instead. The layout is in `docs/reference/dataset-layout.md`.

**Bokeh appears once Stage C has run.** It writes `bokeh/<frame>.png` into each sequence, so a `"*/bokeh/*.png"` argument to `vpv` adds the pane.

## Notes

- The legacy `commands.txt` at the repo root is superseded by the VPV section above. Safe to delete once you've confirmed nothing else references it.
- All `uv run python` commands assume the backend env is installed; if a stage fails on import, run `uv sync --extra library` from the repo root first.
- `--device auto` picks CUDA → MPS → CPU. On a Mac, MPS is fine for `da2-small`; `da2-large` is much slower on MPS than on a CUDA box.
