---
license: cc-by-nc-4.0
pretty_name: Video Bokeh Library
task_categories:
- image-to-image
- video-to-video
- depth-estimation
tags:
- image
- bokeh
- depth-of-field
- disparity
- matting
- alpha-matte
- synthetic-data
- compositing
size_categories:
- 10K<n<100K
source_datasets:
- OneOverZero/MAGICK
- BG-20k
viewer: false
---

# Video Bokeh Library

Cut-out objects and background photos, each with a disparity map, for composing training
video for depth-aware bokeh. The library holds $foregrounds foregrounds and
$backgrounds backgrounds. Stage A of
[video-bokeh](https://github.com/ViacheslavDanilov/video-bokeh) built it once. Stage B of
the same code places the foregrounds over a background as moving objects at disparities it
assigns, so every generated frame comes with its mattes, its disparity and its bokeh.
$preview$status
## At a glance

| | foregrounds | backgrounds |
|---|---|---|
| items | $foregrounds | $backgrounds |
| image size | $fg_side × $fg_side | $bg_side × $bg_side |
| files per item | `rgb.png`, `alpha.png`, `depth.png`, `meta.json` | `rgb.png`, `depth.png` |
| tar shards | $fg_shards | $bg_shards |
| size | $fg_gb GB | $bg_gb GB |

- **$shards shards, $total_gb GB in all.** The largest shard is $largest_gb GB.
- **Disparity, not depth.** Larger values are closer.
- **One estimator.** Every map comes from Depth Anything V2 Large.

## Quick start

`fetch` downloads the shards one at a time and unpacks each into a library folder, so the
disk needs $total_gb GB for the library plus room for one shard. Run again, it downloads only
the shards it has not unpacked yet. It needs Python 3.13 and
[uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ViacheslavDanilov/video-bokeh
cd video-bokeh/backend
uv sync --no-dev --extra loader
uv run python -m video_bokeh.library.hub fetch --repo $repo --output data/library/da2-large
```

The folder it writes is the layout Stage B reads:

```text
data/library/da2-large/
├── foregrounds/<id>/rgb.png, alpha.png, depth.png, meta.json
└── backgrounds/<id>/rgb.png, depth.png
```

The sequence stream turns it into training data in memory. Each item is a new sequence,
generated on the fly and never written to disk:

```python
from pathlib import Path

from video_bokeh.loader import SequenceStream

stream = SequenceStream(
    Path("data/library/da2-large"),
    n_frames=8,
    size=256,
    streams=("rgb", "disparity", "bokeh"),
)
item = next(iter(stream))
print(item["rgb"].shape, item["disparity"].shape, item["bokeh"].shape)
# torch.Size([8, 3, 256, 256]) torch.Size([8, 1, 256, 256]) torch.Size([8, 3, 256, 256])
```

`uv run python -m video_bokeh.loader.example --library-root data/library/da2-large` trains a
small network on it for 20 steps. The repository's README shows how to write sequences to disk
instead, with optical flow and the layers each frame is composited from.

To read one item without the code, open its files with Pillow and NumPy:

```python
import numpy as np
from PIL import Image

item = "data/library/da2-large/foregrounds/<id>"
rgba = np.asarray(Image.open(f"{item}/rgb.png"))  # (H, W, 4) uint8
matte = np.asarray(Image.open(f"{item}/alpha.png")) / 255.0  # (H, W) in [0, 1]
disparity = np.asarray(Image.open(f"{item}/depth.png")) / 65535.0  # (H, W) in [0, 1]
```

## Repository layout

```text
README.md
index.json$assets
foregrounds/foregrounds-00000.tar … $fg_last
backgrounds/backgrounds-00000.tar … $bg_last
```

- **A shard is a plain tar.** The images are PNG already, so it is not compressed again.
- **A shard holds whole items.** Its members are `foregrounds/<id>/rgb.png` and the other
  files of the item, so unpacking every shard into one folder gives the layout above.
- **`index.json` lists the shards of each kind**, with the number of items and the bytes each
  holds. `fetch` reads it first.
- **The viewer is off.** The shards group files by folder, not by WebDataset's file-name
  prefix, so the viewer would show each file as a sample of its own.

## What each file holds

| file | mode | type | values |
|---|---|---|---|
| `foregrounds/<id>/rgb.png` | RGBA | uint8 | the cut-out, with its matte as alpha |
| `foregrounds/<id>/alpha.png` | L | uint8 | the matte, 0 transparent to 255 opaque |
| `foregrounds/<id>/depth.png` | I;16 | uint16 | disparity over the whole square, 0 far to 65535 near |
| `foregrounds/<id>/meta.json` | JSON | | how the item was made |
| `backgrounds/<id>/rgb.png` | RGB | uint8 | the photo |
| `backgrounds/<id>/depth.png` | I;16 | uint16 | disparity, 0 far to 65535 near |

- **Each disparity map is scaled to its own range.** Its smallest value is stored as 0 and its
  largest as 65535. Values cannot be compared across items, and no map holds metric depth.
  Stage B stretches every map into the band of disparity it assigns, so only the shape inside
  a map matters.
- **A foreground's disparity covers the whole square.** Inside the matte it is the estimator's.
  Outside, it is copied from the nearest trusted pixel and blurred. Stage B reads it only
  where the matte is above 0, and the preview draws only that part.
- **Ids name the source image.** A foreground id is MAGICK's image path without its extension,
  with `__` for the slash. A background id is BG-20k's split and file name the same way,
  `train__h_…` or `testval__h_…`.
- **`meta.json`** records the estimator, the source image, the cleanup settings below and
  statistics of the raw estimate, such as `core_frac`, the share of the square the trusted
  core covers, and `low_confidence`, true when that core is under 0.2 % of it.

## How it was built

1. **Foregrounds.** We started from 11,868 hand-picked MAGICK images. A zero-shot
   classifier, Perception Encoder (PE-Core-bigG-14-448, run through OpenCLIP), labeled each
   with a subject and a style. We kept the subjects person, animal, plant, food and object,
   in the styles photo and render, with a subject score of at least 0.5. That keeps 8,586 of
   them in the full library. Each was resized on its shorter side and center-cropped to
   $fg_side × $fg_side. Its alpha channel is the matte. No matting model ran.
2. **Backgrounds.** All $backgrounds BG-20k images, resized and center-cropped to
   $bg_side × $bg_side. That leaves a quarter of a $fg_side-pixel frame to spare on every
   side, so Stage B can pan and zoom without leaving the photo.
3. **Disparity.** Depth Anything V2 Large (`depth-anything/Depth-Anything-V2-Large-hf`) ran
   once on every image. The model cannot read transparency, so each cut-out was first pasted
   onto a fixed texture of soft gray noise.
4. **Foreground cleanup.** The matte, from alpha 0.04 up, was eroded by 5 pixels. Pixels in it
   below the 2nd percentile of disparity were dropped, because they are holes the model left,
   often in hair. What remains is the trusted core. Every pixel outside it takes the value of
   its nearest core pixel, smoothed with a Gaussian blur of sigma 3.
5. **Storage.** Every map was scaled to its own range and written as a 16-bit PNG.

## Limitations

- **The disparity is a model's estimate, not a measurement.** It is relative, and it can be
  wrong, most visibly at thin structures such as hair.
- **The foregrounds are generated images, not photos.** MAGICK made them with a text-to-image
  model and cut them out by chroma keying.
- **The subjects are uneven.** Of the 8,586 foregrounds of the full library, 3,974 are
  people, 2,327 objects, 1,406 food, 483 plants and 396 animals, by the classifier's labels.
- **The labels are not shipped.** The classifier's subject and style of each foreground stay
  in the code repository, in `backend/data/magick/predictions.csv`, keyed by `page_id`, the
  part of a foreground id after `__`.
- **Non-commercial use only.** The license below follows from the sources.

## Sources and license

The library is released under CC BY-NC 4.0, for non-commercial research. It holds images of
two datasets, resized and cropped, and the output of one model:

| part | source | license |
|---|---|---|
| foregrounds | [MAGICK](https://huggingface.co/datasets/OneOverZero/MAGICK) (Burgert et al., CVPR 2024) | CC BY-NC 4.0, as its [project page](https://ryanndagreat.github.io/MAGICK/) states |
| backgrounds | [BG-20k](https://github.com/JizhiziLi/GFM) (Li et al., IJCV 2022) | MIT, on condition that papers using it cite Li et al.; each image's copyright stays with its owner |
| disparity | [Depth Anything V2 Large](https://huggingface.co/depth-anything/Depth-Anything-V2-Large-hf) (Yang et al., NeurIPS 2024) | weights CC BY-NC 4.0 |

BG-20k's terms are in its
[release agreement](https://jizhizili.github.io/files/gfm_datasets_agreements/BG-20k_Dataset_Release_Agreement.pdf).
Its paper says the photos were collected from Unsplash and Pexels; each photo's copyright
stays with its owner.

## Citation

If you use the library, please cite the three works it is built from:

```bibtex
@InProceedings{burgert2024magick,
    author    = {Burgert, Ryan D. and Price, Brian L. and Kuen, Jason and Li, Yijun and Ryoo, Michael S.},
    title     = {MAGICK: A Large-scale Captioned Dataset from Matting Generated Images using Chroma Keying},
    booktitle = {Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)},
    month     = {June},
    year      = {2024},
    pages     = {22595-22604}
}

@article{li2022bridging,
  title={Bridging Composite and Real: Towards End-to-End Deep Image Matting},
  volume={130},
  ISSN={1573-1405},
  url={http://dx.doi.org/10.1007/s11263-021-01541-0},
  DOI={10.1007/s11263-021-01541-0},
  number={2},
  journal={International Journal of Computer Vision},
  publisher={Springer Science and Business Media LLC},
  author={Li, Jizhizi and Zhang, Jing and Maybank, Stephen J. and Tao, Dacheng},
  year={2022},
  month=Jan,
  pages={246--266}
}

@inproceedings{yang2024depthanythingv2,
  author = {Yang, Lihe and Kang, Bingyi and Huang, Zilong and Zhao, Zhen and Xu, Xiaogang and Feng, Jiashi and Zhao, Hengshuang},
  booktitle = {Advances in Neural Information Processing Systems},
  doi = {10.52202/079017-0688},
  editor = {A. Globerson and L. Mackey and D. Belgrave and A. Fan and U. Paquet and J. Tomczak and C. Zhang},
  pages = {21875--21911},
  publisher = {Curran Associates, Inc.},
  title = {{Depth Anything V2}},
  url = {https://proceedings.neurips.cc/paper_files/paper/2024/file/26cfdcd8fe6fd75cc53e92963a656c58-Paper-Conference.pdf},
  volume = {37},
  year = {2024}
}
```
