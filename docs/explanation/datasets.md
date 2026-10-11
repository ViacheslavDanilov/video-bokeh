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

[[magick]] provides isolated objects with alpha channels.
`video_bokeh.acquire.magick` fetches images from
[OneOverZero/MAGICK on Hugging Face](https://huggingface.co/datasets/OneOverZero/MAGICK).
The development pool contains 30 foregrounds. Stage A's default CLIP filter keeps 17.

## Backgrounds

BG-20k provides the background images.
`video_bokeh.acquire.bg20k` uses `kagglehub` to fetch the
[Kaggle upload](https://www.kaggle.com/datasets/nguyenquocdungk16hl/bg-20o).
It can download the full archive or grow a sample one image at a time.
The tracked development pool contains 30 backgrounds.

## Generated sequences

Stage A builds the artifact library from these pools.
Stage B samples scenes and writes sequences. The layered renderer can produce bokeh during
Stage B or run afterward as Stage C over saved layers.

- [[generate-a-dataset]] has the acquisition, library, generation, and rendering recipes.
- [[dataset-layout]] defines the files and formats each stage writes.
- [[demo-unrestricted-trajectories]] explains how to check motion and depth by eye.
