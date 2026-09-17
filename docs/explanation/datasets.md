---
type: topic
status: active
tags: [topic, datasets]
---

# Datasets

Index of datasets used or considered for the video-bokeh project. Group them by purpose.

## Foreground / RGBA

- **[[magick]]** — RGBA isolated objects (chroma-keying pipeline; alpha computed post-hoc).
- **[[layer-diffuse]]** outputs — RGBA from joint generation (preferred for training data quality).
- **animal-matting** — [bruinxiong/animal-matting](https://github.com/bruinxiong/animal-matting). Animal subjects with mattes.
- **U²-Net outputs** — [xuebinqin/u-2-net](https://github.com/xuebinqin/u-2-net). Salient object detection / matting.

## Backgrounds

- **BG-20K** — [bghira/BG20K on HuggingFace](https://huggingface.co/datasets/bghira/BG20K). 20K natural background images, no foreground subjects.

## Video RGBA (transparent video)

- **[[wan-alpha]] dataset** — not fully released; methodology + partial data + scripts. See [issue #6](https://github.com/WeChatCV/Wan-Alpha/issues/6).

## Building our own data

- **[[generate-a-dataset]]** — how to run the two-stage pipeline: build the artifact library, then generate sequences.
- **[[dataset-layout]]** — what the pipeline writes to disk, with formats and bit depths.

## Cross-references

- For our pipeline choice debate (LayerDiffuse vs MAGICK), see [[layer-diffuse]] and [[magick]].
- For depth-estimation datasets / DepthPro vs DepthAnything testing, see [[2026-01-07-huawei-sync]].
