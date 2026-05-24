# Scripts

Copy-paste recipes for building, analyzing, and visualizing the synthetic dataset. Run every command from the repo root unless noted.

## Build a synthetic dataset

`build_dataset.py` chains four stages: CLIP classification → sequence rendering → disparity estimation → any-to-bokeh layout. The orchestrator stops after stage 4; run any-to-bokeh by hand from its own env (see below).

### Dev build — fast iteration (~minutes)

20-image dev splits of MAGICK and BG-20k, `da2-small` depth model, `predictions.csv` skipped because `magick_dev/predictions.csv` ships with the repo.

```bash
uv run python scripts/build_dataset.py --fg-data-root backend/data/magick_dev --bg-data-root backend/data/bg-20k_dev --output backend/data/synth_dev_new --count 3 --depth-model da2-small --skip classify
```

If the `keep_confidence` filter drops too many of the 20 dev foregrounds, disable both axis thresholds:

```bash
uv run python scripts/build_dataset.py --fg-data-root backend/data/magick_dev --bg-data-root backend/data/bg-20k_dev --output backend/data/synth_dev_new --count 3 --depth-model da2-small --subject-thr 0.0 --style-thr 0.0 --skip classify
```

Force a full re-run including the 20-image CLIP pass (about 30 seconds on MPS):

```bash
uv run python scripts/build_dataset.py --fg-data-root backend/data/magick_dev --bg-data-root backend/data/bg-20k_dev --output backend/data/synth_dev_new --count 3 --depth-model da2-small --batch-size 8
```

### Production build — full datasets (~30+ minutes)

Full MAGICK (12k FGs) + BG-20k, `da2-large` for spatial precision.

```bash
uv run python scripts/build_dataset.py --fg-data-root backend/data/magick --bg-data-root backend/data/bg-20k_dev --output backend/data/synth_dev_new --count 10 --seed 0 --depth-model da2-large
```

### Resume after a crash

Stage short names: `classify`, `generate`, `disparity`, `prepare`. List whichever stages already produced their output.

Resume from disparity (sequences + `predictions.csv` already exist):

```bash
uv run python scripts/build_dataset.py --fg-data-root backend/data/magick --bg-data-root backend/data/bg-20k_dev --output backend/data/synth_dev_new --count 10 --depth-model da2-large --skip classify,generate
```

Re-do only the a2b layout:

```bash
uv run python scripts/build_dataset.py --fg-data-root backend/data/magick --bg-data-root backend/data/bg-20k_dev --output backend/data/synth_dev_new --count 10 --depth-model da2-large --skip classify,generate,disparity
```

### Run any-to-bokeh after the pipeline finishes

a2b has its own Python env under `backend/third_party/any-to-bokeh/`. Make sure that env is installed first.

```bash
cd backend/third_party/any-to-bokeh && python test/inference_demo.py --val_csv_path csv_file/synth_dev_new.csv
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
cd backend/data/synth_dev_new/sequences && vpv */all_in_focus/*.png */alpha/*.png */alpha_layers/*.png
```

### Cross-dataset view (composite + alpha_layers + a2b bokeh output)

Run from the repo root with quoted globs so `vpv` does the expansion. This is the end-to-end review once any-to-bokeh has run:

```bash
vpv 'backend/data/synth_dev_new/sequences/*/all_in_focus/*.png' 'backend/data/synth_dev_new/sequences/*/alpha_layers/*.png' 'backend/third_party/any-to-bokeh/demo_dataset/synth_dev_new/disp/*/*.png'
```

## Notes

- The legacy `commands.txt` at the repo root is superseded by the VPV section above. Safe to delete once you've confirmed nothing else references it.
- All `uv run python` commands assume the backend env is installed; if a stage fails on import, run `uv sync` from the repo root first.
- `--device auto` picks CUDA → MPS → CPU. On a Mac, MPS is fine for `da2-small`; `da2-large` is much slower on MPS than on a CUDA box.
