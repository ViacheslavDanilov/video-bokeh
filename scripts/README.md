# Scripts

These scripts set up model environments, run the lab checks, and analyze the source data.
Run commands from the repository root.

## Set up any-to-bokeh

`setup_third_party.sh` initializes the submodule, creates its Python 3.10 environment, and
caches its checkpoints. It needs an NVIDIA machine. See
[Run any-to-bokeh inference](../docs/how-to/run-any-to-bokeh-inference.md).

```bash
scripts/setup_third_party.sh
```

## Set up Depth Anything 3

`setup_depth_anything_3.sh` creates the Python 3.12 environment used by the local DA3
estimators. See [Depth Anything 3's own environment](../docs/reference/cli.md#depth-anything-3s-own-environment).

## Run the lab checks

`lab_run.sh` measures the depth estimators, builds libraries, generates sequences, renders
bokeh, and packs videos into one logged run. See
[Run on the lab machine](../docs/how-to/run-on-the-lab-machine.md).

## Analyze the MAGICK filter

`analyze_magick_distribution.py` plots the CLIP keep curves and writes `summary.json` under
`docs/attachments/2026-05-20-magick-distribution/`. See
[MAGICK dataset](../docs/explanation/magick.md) for the source and filter.

```bash
uv run python scripts/analyze_magick_distribution.py
```
