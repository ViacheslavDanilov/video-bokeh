---
type: topic
status: active
tags: [topic, dataset, generation, rgba]
related: [datasets, generate-a-dataset, dataset-layout]
---

# MAGICK dataset

MAGICK supplies the pipeline's foreground images with red, green, blue, and alpha (RGBA)
channels. We download existing images from
[OneOverZero/MAGICK on Hugging Face](https://huggingface.co/datasets/OneOverZero/MAGICK).
We do not generate new foreground images or run a separate matting model.

## Source pools

`video_bokeh.acquire.magick` downloads a sample named by the checked-in metadata.
It preserves the upstream `images/<prefix>/<page_id>.png` layout.
The full mirror uses the same layout, so Stage A can read either pool.

The tracked development pool holds 30 foregrounds.
The full-set metadata and CLIP predictions are tracked too, while the full image mirror
stays local. Acquisition recipes are in [generate-a-dataset](../how-to/generate-a-dataset.md).

## Filtering for Stage A

Stage A selects assets using the stored CLIP subject and style scores.
The default filter keeps the subjects person, animal, plant, food, and object, in the styles
photo and render. It keeps 17 of the 30 development foregrounds.
The flags and thresholds are in [cli](../reference/cli.md).

`scripts/analyze_magick_distribution.py` reads the full-set predictions and plots how many
assets survive each threshold. Its plots and `summary.json` go to
`docs/attachments/2026-05-20-magick-distribution/` and stay local.

## Alpha in our pipeline

The source image's alpha channel is the foreground matte throughout the pipeline.
Stage A stores it with the asset. Stage B transforms it with the object and writes one TIFF
page per object in each frame. [dataset-layout](../reference/dataset-layout.md) describes the output formats.

## Upstream references

- [Repository](https://github.com/RyannDaGreat/MAGICK)
- [Project page](https://ryanndagreat.github.io/MAGICK/)
- [Image grid explorer](https://ryanndagreat.github.io/MAGICK/Explorer/magick_rgba_explorer.html)
