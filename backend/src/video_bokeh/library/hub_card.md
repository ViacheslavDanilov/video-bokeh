---
license: cc-by-nc-4.0
pretty_name: Video Bokeh
task_categories:
- image-to-image
- depth-estimation
tags:
- image
- video
- bokeh
- depth-of-field
- disparity
- optical-flow
- matting
- alpha-matte
- synthetic-data
- compositing
size_categories:
- 10K<n<100K
source_datasets:
- OneOverZero/MAGICK
- BG-20k
configs:
- config_name: foregrounds
  data_files:
  - split: train
    path: "library/foregrounds/train-*.tar"
  - split: test
    path: "library/foregrounds/test-*.tar"
  default: true
- config_name: backgrounds
  data_files:
  - split: train
    path: "library/backgrounds/train-*.tar"
  - split: test
    path: "library/backgrounds/test-*.tar"
$sequences_config---

# Video Bokeh

Synthetic video for training and evaluating depth-aware bokeh. Every frame is composited
from known layers, so its disparity, the soft matte of each object, its bokeh, its forward
and backward optical flow and its occlusion match it by construction. The
[code](https://github.com/ViacheslavDanilov/video-bokeh) that makes them is open.

- **The library**, under `library/`: $foregrounds cut-out foregrounds and $backgrounds
  background photos, each with a disparity map. It holds no sequences. The code's generator
  composes new ones from it while a network trains, as many as the training asks for.$sequences_part

The code works in two stages. Stage A built the library once, from MAGICK and BG-20k images
and Depth Anything V2 Large. Stage B, the generator, moves the foregrounds over a background
at disparities it draws for each object and renders every stream of every frame.
$preview$status
## At a glance

$glance

## Train and test

**Every asset is in the train split or the test split.** The backgrounds follow BG-20k's own
split. MAGICK has no split, so 10% of the foregrounds of each subject were drawn once, with a
fixed seed, for the test split; the code lists them in
`backend/src/video_bokeh/core/test_foregrounds.txt`.

| | Train | Test |
|---|---|---|
| Foregrounds | $fg_train | $fg_test |
| Backgrounds | $bg_train | $bg_test |

The generator draws from the train split unless it is told otherwise, by `split="test"` in
`SequenceStream` or `--split test` in `scenes.generate`.$split_use There is no
validation split: draw one from the train split, with seeds far from the training run's.

## Quick start

It needs Python 3.13, [uv](https://docs.astral.sh/uv/) and $total_gb GB of disk for the
library, plus room for one shard of at most $largest_gb GB.

```bash
git clone https://github.com/ViacheslavDanilov/video-bokeh
cd video-bokeh/backend
uv sync --no-dev --extra loader
uv run python -m video_bokeh.library.hub fetch --repo $repo --output data/library/da2-large
```

`fetch` downloads the shards one at a time and unpacks each into the layout the generator
reads. A second run downloads only the shards the first did not unpack.

```text
data/library/da2-large/
├── foregrounds/<id>/rgb.png, alpha.png, depth.png, meta.json
└── backgrounds/<id>/rgb.png, depth.png
```

`SequenceStream`, the project's PyTorch dataset, runs the generator on that folder in
memory. Each item is a new sequence, never written to disk:

```python
from pathlib import Path

from video_bokeh.loader import SequenceStream

stream = SequenceStream(
    Path("data/library/da2-large"),
    n_frames=8,
    size=256,
    streams=("rgb", "disparity", "bokeh"),
    bokeh_strength=16.0,
)
item = next(iter(stream))
print(item["rgb"].shape, item["disparity"].shape, item["bokeh"].shape)
# torch.Size([8, 3, 256, 256]) torch.Size([8, 1, 256, 256]) torch.Size([8, 3, 256, 256])
```

`n_frames` and `size` set a sequence's length and the side of its frames, and `streams`
what an item carries. `bokeh_strength` is the bokeh's strength `k`: the blur radius, in
pixels at a 1024-pixel width, of a point one unit of disparity from the focus.
`uv run python -m video_bokeh.loader.example --library-root data/library/da2-large` trains a
small network on the stream for 20 steps, and the project's
[README](https://github.com/ViacheslavDanilov/video-bokeh) shows how to write sequences to
disk instead.
$fixed_set
## Read the files without the code

A library item is plain PNG, read with Pillow and NumPy:

```python
import numpy as np
from PIL import Image

item = "data/library/da2-large/foregrounds/<id>"
rgba = np.asarray(Image.open(f"{item}/rgb.png"))  # (H, W, 4) uint8
matte = np.asarray(Image.open(f"{item}/alpha.png")) / 255.0  # (H, W) in [0, 1]
disparity = np.asarray(Image.open(f"{item}/depth.png")) / 65535.0  # (H, W) in [0, 1]
```

The `datasets` library streams the shards from the Hub with no download, one sample per
item, which is enough to inspect them:

```python
from datasets import load_dataset

foregrounds = load_dataset("$repo", "foregrounds", split="train", streaming=True)
item = next(iter(foregrounds))
# keys: rgb.png, alpha.png, depth.png, depth_preview.jpg, json, __key__ (the id), __url__
```
$sequences_datasets
## Library files

| File | Mode | Type | Values |
|---|---|---|---|
| `foregrounds/<id>/rgb.png` | RGBA | uint8 | the cut-out, with its matte as alpha |
| `foregrounds/<id>/alpha.png` | L | uint8 | the matte, 0 transparent to 255 opaque |
| `foregrounds/<id>/depth.png` | I;16 | uint16 | disparity over the whole square, 0 far to 65535 near |
| `foregrounds/<id>/meta.json` | JSON | | how the item was made |
| `backgrounds/<id>/rgb.png` | RGB | uint8 | the photo |
| `backgrounds/<id>/depth.png` | I;16 | uint16 | disparity, 0 far to 65535 near |

- **Each disparity map is scaled to its own range,** its smallest value to 0 and its largest
  to 65535. Values cannot be compared across items, and no map holds metric depth. The
  generator stretches each map into the band of disparity it draws for the object, so only
  the shape inside a map matters.
- **A foreground's disparity covers the whole square.** Inside the trusted core (step 4 of
  How it was built) it is the estimator's. Everywhere else, the matte's edge and the holes
  the cleanup dropped included, it is copied from the nearest core pixel and blurred, since
  the generator reads it wherever the matte is above 0.
- **Ids name the source image,** with `__` for the slash. A foreground id is MAGICK's image
  path without its extension. A background id is BG-20k's split folder and file name,
  `train__h_…` or `testval__h_…`.
- **`meta.json`** records the estimator, the source image, the cleanup settings and
  statistics of the raw estimate, such as `core_frac`, the share of the square the trusted
  core covers, and `low_confidence`, true when that core is under 0.2% of it.

## Repository layout

```text
README.md$assets
library/index.json
$layout
```

- **A shard is a plain tar in WebDataset's layout, of whole items of one split.** An item's
  files share its id, as `<id>.rgb.png`, `<id>.alpha.png`, `<id>.depth.png` and `<id>.json`.
  The images are PNG already, so the tar is not compressed again.
- **Each library item also holds `<id>.depth_preview.jpg`,** its disparity in color, for the
  Hub's viewer. `fetch` leaves it out.
- **`library/index.json` lists each kind's shards** with their split, item count and bytes.
  `fetch` reads it first.

## How it was built

1. **Foregrounds.** We started from the 11,868 MAGICK images its authors picked by hand.
   A zero-shot classifier, Perception Encoder (PE-Core-bigG-14-448, run through OpenCLIP),
   labeled each with a subject and a style. We kept the subjects person, animal, plant, food
   and object, in the styles photo and render, with a subject score of at least 0.5. That
   leaves 8,586. Each was resized on its shorter side and center-cropped to
   $fg_side × $fg_side. Its alpha channel is the matte. No matting model ran.
2. **Backgrounds.** All $backgrounds BG-20k images, resized and center-cropped to
   $bg_side × $bg_side. That leaves a quarter of a $fg_side-pixel frame to spare on every
   side, so the generator can pan and zoom without leaving the photo.
3. **Disparity.** Depth Anything V2 Large (`depth-anything/Depth-Anything-V2-Large-hf`) ran
   once on every image. The model cannot read transparency, so each cut-out was first pasted
   onto a fixed texture of soft noise around mid-gray.
4. **Foreground cleanup.** The matte, from alpha 0.04 up, was eroded by 5 pixels. Pixels in it
   below the 2nd percentile of disparity were dropped, because they are holes the model left,
   often in hair. What remains is the trusted core. Every pixel outside it takes the value of
   its nearest core pixel, smoothed with a Gaussian blur of sigma 3.
5. **Storage.** Every map was scaled to its own range and written as a 16-bit PNG.

## Limitations

- **The disparity is a model's estimate.** It is relative, and it can be wrong, most visibly
  at thin structures such as hair.
- **The foregrounds are generated.** MAGICK made them with a text-to-image model and cut
  them out by chroma keying.
- **The bokeh is a renderer's, not a lens's.** The project's layered renderer blurs each layer
  by its disparity, so a network trained on it learns that renderer.
- **The mattes carry a faint halo.** Around most foregrounds, MAGICK's matte holds alpha
  under 0.04 well past the visible edge, covering 3.8% of the square for the median
  foreground. The generator composites it as it is, so each halo pixel carries under 4% of
  the foreground's color and disparity into a frame.
- **The split is by image, not by prompt.** MAGICK made several images from some prompts, and
  144 of the 859 test foregrounds share their prompt, word for word, with a train
  foreground.
- **The subjects are uneven.** Of the 8,586 foregrounds, 3,974 are people, 2,327 objects,
  1,406 food, 483 plants and 396 animals, by the classifier's labels. The labels are not
  shipped: they stay in the code repository, in `backend/data/magick/predictions.csv`, keyed
  by `page_id`, the part of a foreground id after `__`.

## Sources and license

The dataset is released under CC BY-NC 4.0, for non-commercial research only, as its sources
require. It holds images of two datasets, resized and cropped, and the output of one model:

| Part | Source | License |
|---|---|---|
| Foregrounds | [MAGICK](https://huggingface.co/datasets/OneOverZero/MAGICK) (Burgert et al., CVPR 2024) | CC BY-NC 4.0, as its [project page](https://ryanndagreat.github.io/MAGICK/) states |
| Backgrounds | [BG-20k](https://github.com/JizhiziLi/GFM) (Li et al., IJCV 2022) | MIT, on condition that papers using it cite Li et al.; each image's copyright stays with its owner |
| Disparity | [Depth Anything V2 Large](https://huggingface.co/depth-anything/Depth-Anything-V2-Large-hf) (Yang et al., NeurIPS 2024) | weights CC BY-NC 4.0 |

## Citation

If you use this dataset, please cite it:

```bibtex
@misc{danilov2026videobokeh,
  author       = {Danilov, Viacheslav and Dewil, Valéry and Arias, Pablo},
  title        = {{Video Bokeh}},
  year         = {2026},
  publisher    = {Hugging Face},
  howpublished = {\url{https://huggingface.co/datasets/$repo}}
}
```
