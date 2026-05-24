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
3. Prints the remaining manual step: download the UNet + VAE checkpoints from Google Drive (linked in the script output) and extract them under `backend/third_party/any-to-bokeh/checkpoints/unet/` and `.../vae/`. This path matches `inference_demo.py`'s defaults and is gitignored by the a2b submodule.

The Stable Video Diffusion base model used by any-to-bokeh is pulled from HF on first inference; `huggingface-cli login` first if you've gated that model.

Activate the venv before running any-to-bokeh:

```bash
source backend/third_party/any-to-bokeh/.venv/bin/activate
```

The main backend env (used by every command in the sections below) is separate — managed by `uv sync` from the repo root.

## Build a synthetic dataset

`build_dataset.py` chains four stages: CLIP classification → sequence rendering → disparity estimation → any-to-bokeh layout. The orchestrator stops after stage 4; run any-to-bokeh by hand from its own env (see below).

### Dev build — fast iteration (~minutes)

20-image dev splits of MAGICK and BG-20k, `da2-small` depth model, `predictions.csv` skipped because `magick_dev/predictions.csv` ships with the repo.

```bash
uv run python scripts/build_dataset.py --fg-data-root backend/data/magick_dev --bg-data-root backend/data/bg-20k_dev --output backend/data/synth_dev --count 3 --depth-model da2-small --skip classify
```

If the `keep_confidence` filter drops too many of the 20 dev foregrounds, disable both axis thresholds:

```bash
uv run python scripts/build_dataset.py --fg-data-root backend/data/magick_dev --bg-data-root backend/data/bg-20k_dev --output backend/data/synth_dev --count 3 --depth-model da2-small --subject-thr 0.0 --style-thr 0.0 --skip classify
```

Force a full re-run including the 20-image CLIP pass (about 30 seconds on MPS):

```bash
uv run python scripts/build_dataset.py --fg-data-root backend/data/magick_dev --bg-data-root backend/data/bg-20k_dev --output backend/data/synth_dev --count 3 --depth-model da2-small --batch-size 8
```

### Production build — full datasets (~30+ minutes)

Full MAGICK (12k FGs) + BG-20k, `da2-large` for spatial precision.

```bash
uv run python scripts/build_dataset.py --fg-data-root backend/data/magick --bg-data-root backend/data/bg-20k_dev --output backend/data/synth_dev --count 10 --seed 0 --depth-model da2-large
```

### Resume after a crash

Stage short names: `classify`, `generate`, `disparity`, `prepare`. List whichever stages already produced their output.

Resume from disparity (sequences + `predictions.csv` already exist):

```bash
uv run python scripts/build_dataset.py --fg-data-root backend/data/magick --bg-data-root backend/data/bg-20k_dev --output backend/data/synth_dev --count 10 --depth-model da2-large --skip classify,generate
```

Re-do only the a2b layout:

```bash
uv run python scripts/build_dataset.py --fg-data-root backend/data/magick --bg-data-root backend/data/bg-20k_dev --output backend/data/synth_dev --count 10 --depth-model da2-large --skip classify,generate,disparity
```

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
vpv 'backend/data/synth_dev/sequences/*/all_in_focus/*.png' 'backend/data/synth_dev/sequences/*/alpha_layers/*.png' 'backend/third_party/any-to-bokeh/demo_dataset/synth_dev/disp/*/*.png'
```

## Notes

- The legacy `commands.txt` at the repo root is superseded by the VPV section above. Safe to delete once you've confirmed nothing else references it.
- All `uv run python` commands assume the backend env is installed; if a stage fails on import, run `uv sync` from the repo root first.
- `--device auto` picks CUDA → MPS → CPU. On a Mac, MPS is fine for `da2-small`; `da2-large` is much slower on MPS than on a CUDA box.
