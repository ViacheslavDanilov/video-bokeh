---
type: reference
status: active
tags: [reference, cli, flags]
related: [dataset-layout, generate-a-dataset]
---

# CLI reference

Every flag of every `data.*` module, read out of the `argparse` parsers. Defaults here are
the parser's defaults, not what a recipe happens to pass.

All commands run from `backend/` and go through `uv run`, so they use the locked environment:

```bash
uv run python -m data.<module> [flags]
```

---

## `data.build_library` — Stage A

Estimates depth once per asset and writes the artifact library.

| flag | type | default | meaning |
|---|---|---|---|
| `--fg-data-root` | path | **required** | MAGICK-style foreground pool |
| `--bg-data-root` | path | **required** | BG-20k-style background pool |
| `--output` | path | **required** | library root to write |
| `--size` | int | `1024` | square side for foreground assets |
| `--model` | str | `da2-large` | `da2-small`, `da2-base`, `da2-large` |
| `--device` | str | `auto` | `auto`, `cuda`, `mps`, `cpu` |
| `--neutral-bg-seed` | int | `0` | seed for the synthetic neutral backdrop |
| `--bg-margin` | float | `0.25` | padding around the object on that backdrop |
| `--nb-pixels-remove` | int | `5` | edge pixels trimmed before depth propagation |
| `--alpha-threshold` | float | `0.04` | alpha below this is treated as background |
| `--low-pct` | float | `2.0` | low percentile clipped when normalizing depth |
| `--limit-fg` | int | all | cap on foregrounds processed |
| `--limit-bg` | int | all | cap on backgrounds processed |
| `--subjects` | list | `person, animal, plant, food, object` | CLIP subject classes kept |
| `--styles` | list | `photo, render` | CLIP style classes kept |
| `--subject-thr` | float | `0.5` | minimum CLIP score to keep an asset |

## `data.generate_dataset` — Stage B

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
| `--n-objects-max` | int | `3` | most objects. Above 3 the run is refused — see [[dataset-layout]] |

`bg_band_top` is not exposed on the CLI. Changing it needs the Python API.

## `data.prepare_any_to_bokeh` — the inference bridge

| flag | type | default | meaning |
|---|---|---|---|
| `--data-root` | path | **required** | dataset root containing `sequences/` |
| `--a2b-root` | path | `third_party/any-to-bokeh` | vendored inference checkout |
| `--dataset-name` | str | basename of `--data-root` | name under `demo_dataset/` and `csv_file/` |
| `--k` | str | `16` | blur-strength column written to the CSV |
| `--seqs` | list | all | comma-separated sequence ids, e.g. `0001,0003` |
| `--focus-disparity` | float | unset | pin one focus in `[0, 1]` for every frame. Overrides `--focus` |
| `--focus` | str | `alpha` | `alpha` = mean disparity under the mask; `full` = whole frame |

## `data.pack_videos` — PNG streams to MP4

| flag | type | default | meaning |
|---|---|---|---|
| `--data-root` | path | **required** | dataset root containing `sequences/` |
| `--streams` | list | `all_in_focus` | which stream directories to encode |
| `--fps` | int | `24` | frame rate |
| `--quality` | int | `10` | imageio quality, 10 is visually lossless |
| `--seqs` | list | all | comma-separated sequence ids |

Disparity is deliberately unsupported: packing depth into a viewable video needs a colormap
and a normalization choice that belong in a visualization script, not here.

## Acquisition

| module | flags |
|---|---|
| `data.download_magick` | `--metadata` (csv), `--output`, `--count`, `--seed`, `--picked` |
| `data.download_bg20k` | `--output`. Needs `~/.kaggle/kaggle.json` |
| `data.classify_clip` | `--data-root`, `--output`, `--model`, `--pretrained`, `--device`, `--batch-size`, `--num-workers` |

---

## Related

- [[dataset-layout]] — what these commands write
- [[generate-a-dataset]] — the recipes that use them
