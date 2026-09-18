# Scripts

Copy-paste recipes for setting up, building, analyzing, and visualizing the synthetic dataset. Run every command from the repo root unless noted.

## First-time setup on a new machine

`setup_third_party.sh` initializes the `any-to-bokeh` submodule and provisions a dedicated Python 3.10 venv for it under `backend/third_party/any-to-bokeh/.venv`. Each third-party tool owns its own venv — no shared env, so no pin conflicts. CUDA-only — intended for the server.

```bash
scripts/setup_third_party.sh
```

What it does:

1. `git submodule update --init --recursive` to pull `backend/third_party/any-to-bokeh/`.
2. Creates the venv, installs PyTorch 2.4.1 with CUDA 12.4 wheels (override via `CUDA_INDEX_URL=https://download.pytorch.org/whl/cuXYZ`), then installs `any-to-bokeh/requirements.txt`.
3. Downloads the UNet + VAE checkpoints from Google Drive via `uvx gdown` into `backend/third_party/any-to-bokeh/checkpoints/{unet,vae}/`. This path matches `inference_demo.py`'s defaults and is gitignored by the a2b submodule. If `gdown` fails (Drive rate-limit, auth, or quota), the script prints a manual fallback URL.
4. Downloads the Stable Video Diffusion base model (`stabilityai/stable-video-diffusion-img2vid-xt`, ~10 GB fp16) from Hugging Face into `$HF_HOME`. The a2b inference script loads it with `local_files_only=True`, so it **must** be cached before running inference. If you've gated the model, run `huggingface-cli login` before the setup script.

Override the Google Drive file ID with `A2B_CHECKPOINTS_FILE_ID=<id>` if a2b ever republishes the archive.

Activate the venv before running any-to-bokeh:

```bash
source backend/third_party/any-to-bokeh/.venv/bin/activate
```

The main backend env (used by every command in the sections below) is separate — managed by `uv sync` from the repo root.

## Build a synthetic dataset

`build_dataset.py` runs the two stages of the pipeline in order and stops. Bokeh is a
separate pipeline and is not part of it.

1. **Stage A** — estimate depth once per asset and write the artifact library. The slow one.
2. **Stage B** — sample scenes from that library and write sequences. Fast, and repeatable
   from the same library.

### Just run it

```bash
uv run python scripts/build_dataset.py
```

A fresh clone has everything this needs. `backend/data/magick_dev` (20 foregrounds) and
`backend/data/bg-20k_dev` (20 backgrounds) are tracked on purpose, so nothing is downloaded
except the depth model, which Hugging Face caches on first use.

Defaults write `backend/data/library_demo` and `backend/data/demo`: 4 sequences, 24 frames,
512 px, 1 to 5 objects, `da2-small`. **Measured end to end on an M-series Mac: 14 s**, of
which Stage A is 9 s. The script then prints what it wrote and the `vpv` command to look at it.

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
| `--size` | `512` | square frame side. Must match between the two stages, and the script enforces that by passing it to both |
| `--n-objects-min` / `--n-objects-max` | `1` / `5` | objects per scene. Past five the depth axis starts refusing scenes — see `docs/reference/dataset-layout.md` |
| `--model` | `da2-small` | `da2-large` is slower and better |
| `--rebuild-library` | off | rerun Stage A |
| `--seed` | `0` | sequence `i` comes from `seed + i` |

For what lands on disk, read `docs/reference/dataset-layout.md`. For the stages one at a
time, `docs/how-to/generate-a-dataset.md`.

### Run any-to-bokeh after the pipeline finishes

a2b has its own Python env under `backend/third_party/any-to-bokeh/`. Make sure that env is installed first.

```bash
cd backend/third_party/any-to-bokeh && python test/inference_demo.py --val_csv_path csv_file/synth_dev.csv
```

## Analyze the MAGICK CLIP filter distribution

Regenerates the keep-curve plots and `summary.json` sidecar into the output directory configured at the top of the script. Re-run after re-classifying or after editing the keep / exclude sets.

```bash
uv run python scripts/analyze_magick_distribution.py
```

## Visualize sequences with VPV

`vpv` opens an N-pane viewer with synchronized playback across the streams. Run from inside the dataset's `sequences/` directory unless noted.

### Inspect the rendered streams

Composite + union alpha + per-object alpha layers — the standard post-render sanity check:

```bash
cd backend/data/synth_dev/sequences && vpv */all_in_focus/*.png */alpha/*.png */alpha_layers/*.png
```

### Cross-dataset view (composite + alpha_layers + a2b bokeh output)

Run from the repo root with quoted globs so `vpv` does the expansion. This is the end-to-end review once any-to-bokeh has run:

```bash
vpv 'backend/data/synth_dev/sequences/*/all_in_focus/*.png' 'backend/data/synth_dev/sequences/*/bokeh/*.png' 'backend/data/synth_dev/sequences/*/alpha_layers/*.png' 'backend/data/synth_dev/sequences/*/disparity/*.png'
```

## Notes

- The legacy `commands.txt` at the repo root is superseded by the VPV section above. Safe to delete once you've confirmed nothing else references it.
- All `uv run python` commands assume the backend env is installed; if a stage fails on import, run `uv sync` from the repo root first.
- `--device auto` picks CUDA → MPS → CPU. On a Mac, MPS is fine for `da2-small`; `da2-large` is much slower on MPS than on a CUDA box.
