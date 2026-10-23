---
type: topic
status: active
tags: [topic, datasets]
related: [magick, generate-a-dataset, dataset-layout]
---

# Datasets

The pipeline combines MAGICK foregrounds with BG-20k backgrounds.
Both have tracked development pools, so a fresh clone can build a library without
downloading source images.

## Foregrounds

[magick](magick.md) provides isolated objects with alpha channels.
`video_bokeh.acquire.magick` fetches images from
[OneOverZero/MAGICK on Hugging Face](https://huggingface.co/datasets/OneOverZero/MAGICK).
See [magick](magick.md) for the development pool size and Stage A's filter result.

## Backgrounds

BG-20k provides the background images.
`video_bokeh.acquire.bg20k` uses `kagglehub` to fetch the
[Kaggle upload](https://www.kaggle.com/datasets/nguyenquocdungk16hl/bg-20o).
It can download the full archive or grow a sample one image at a time.
The tracked development pool contains 30 backgrounds.

## Generated sequences

Stage A builds the artifact library from these pools.
Stage B samples scenes and writes sequences. The layered renderer produces bokeh in Stage B's
pass, or can render it again afterward over saved layers.

- [generate-a-dataset](../how-to/generate-a-dataset.md) has the acquisition, library,
  generation, and rendering recipes.
- [dataset-layout](../reference/dataset-layout.md) defines the files and formats each stage writes.
- [demo-unrestricted-trajectories](../how-to/demo-unrestricted-trajectories.md) explains how to
  check motion and depth by eye.
