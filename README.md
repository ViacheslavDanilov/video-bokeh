<div align="center">

<img src="frontend/src/app/icon.svg" width="100" alt="Video Bokeh logo">

# Video Bokeh

[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/downloads/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178c6.svg)](https://www.typescriptlang.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black.svg)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

Depth-aware synthetic bokeh pipeline for video, with a FastAPI backend and Next.js frontend.

</div>

## Demo

https://github.com/user-attachments/assets/0b7be719-446f-421c-96d5-78f84a937b30

## Features

- **Synthetic training data with known depth** – Objects composited onto backgrounds at disparities we assign, written as video sequences with one matte per object and 16-bit disparity.
- **Swappable parts** – Depth (Depth Anything V2, Depth Pro, Depth Anything 3 or your own) in Stage A, and bokeh: our layer-wise renderer inside Stage B, or your own over written sequences.
- **Training on the fly** – A PyTorch stream that generates a new sequence for every item.
- **Web demo** – Generate a sequence and compare its streams side by side.

## How It Works

Stage A estimates depth once per asset and stores it as a library. Stage B samples objects, a background and depth trajectories from that library and writes sequences. Bokeh is rendered in the same pass, by our layered renderer, or again afterwards over written sequences that hold their layers. The web demo generates sequences on request. [docs/explanation/pipeline-explainer.md](docs/explanation/pipeline-explainer.md) walks through all of it.

## Tech Stack

| Category | Technologies |
|----------|-------------|
| Backend | Python 3.13, FastAPI, Uvicorn |
| Frontend | TypeScript, Next.js, React, Tailwind CSS |
| Data | NumPy, Pillow, tifffile, matplotlib |
| Models | PyTorch and Hugging Face transformers for depth (Stage A); our layered renderer in PyTorch for bokeh |
| Package Management | uv (backend), pnpm (frontend) |
| Build & CI | Docker, Docker Compose, GitHub Actions |

## Getting Started

### Prerequisites

- Python 3.13+ / [uv](https://docs.astral.sh/uv/)
- Node.js 24+ / [pnpm](https://pnpm.io/)

### Installation & Running

```bash
make setup                          # every backend extra, the frontend, Chromium for the smoke test
make images                         # once, on Linux with an NVIDIA card: Depth Anything 3's Docker image
scripts/setup_depth_anything_3.sh   # once, elsewhere: the venv Depth Anything 3 runs in
make libraries                      # once: one library per depth estimator
make api                            # terminal 1: the API on :8000
make web                            # terminal 2: the page on :3000
```

Open [http://localhost:3000](http://localhost:3000) (frontend) and [http://localhost:8000/docs](http://localhost:8000/docs) (API docs).
`make` alone lists every target, including `make check` and `make smoke`.

The page picks a depth estimator, sets the sequence parameters, generates, and compares the
streams side by side. It needs libraries behind it, one per depth estimator: `make libraries`
builds them with Depth Anything V2 Large, Depth Anything 3 Mono-Large and Depth Pro into the
main checkout's `backend/data/library_dev/<estimator>` from the dev pools, and
`make api` serves them. Depth Anything V2 and Depth Pro run in the backend's own environment.
Depth Anything 3 cannot share it: on Linux with Docker's NVIDIA runtime it runs in an image,
which `make images` builds, and elsewhere in a venv of its own, which
`scripts/setup_depth_anything_3.sh` builds once.
`make api LIBRARY=<path>` serves something else: one library, or a directory of them. Building
a library by hand with Stage A is in [backend/README.md](backend/README.md), the page is in
[frontend/README.md](frontend/README.md), and the endpoints are in
[docs/reference/api.md](docs/reference/api.md).

### With Docker

```bash
cp .env.example .env          # only to serve something other than backend/data/library_dev
docker compose up api
```

The containers are `video-bokeh-api` and `video-bokeh-web`. `api` mounts the libraries
read-only at `/data/library` and writes sequences to `/data/sequences`; both come from
`VIDEO_BOKEH_DATA_ROOT`, which defaults to `backend/data`. Generating a sequence in the container
costs roughly half again what it costs natively — the numbers are in
[docs/reference/api.md](docs/reference/api.md).

## Generate Your Own Dataset

Five steps take you from the source images to written sequences or a training loop. Each one
links the page with the details.

1. **Install** the dataset extras from the repository root, with Python 3.13+ and
   [uv](https://docs.astral.sh/uv/).

   ```bash
   uv sync --no-dev --extra acquire --extra library --extra loader
   ```

   [backend/README.md](backend/README.md) says what each extra installs.

2. **Download the source pools:** 11,868 MAGICK foregrounds from
   [Hugging Face](https://huggingface.co/datasets/OneOverZero/MAGICK) into
   `backend/data/magick`, and the BG-20k backgrounds from
   [Kaggle](https://www.kaggle.com/datasets/nguyenquocdungk16hl/bg-20o) into
   `backend/data/bg-20k`. BG-20k comes as one 13.1 GiB archive. A rerun skips what is already
   there.

   ```bash
   make pools
   ```

   - **No Kaggle account is needed.** kagglehub signs in only for private datasets or ones
     that ask for consent, and it fetched BG-20k with no credentials on 2026-10-22. If Kaggle
     refuses anyway, create an API token at [kaggle.com/settings](https://www.kaggle.com/settings),
     save it as `~/.kaggle/access_token`, and run `make pools` again.
   - **Downloaded by hand instead?** Put BG-20k's images in `backend/data/bg-20k/images/train/`
     and `images/testval/`, and `make pools` skips BG-20k. MAGICK's go in
     `backend/data/magick/images/`, in Hugging Face's `<first two characters>/<page_id>.png`
     layout.
   - **To try the pipeline first, skip this step.** A clone carries 30 foregrounds and 30
     backgrounds in `backend/data/magick_dev` and `backend/data/bg-20k_dev`.

   [generate-a-dataset](docs/how-to/generate-a-dataset.md#full-pools) says what each download
   writes.

3. **Build a library.** Stage A estimates each image's depth once and stores the result. This
   step and the next two run from `backend/`.

   ```bash
   cd backend
   uv run --frozen --no-sync python -m video_bokeh.library.build \
     --fg-data-root data/magick --bg-data-root data/bg-20k \
     --output data/library/da2-large --size 1024 --model da2-large
   ```

   `--model` picks the depth estimator: Depth Anything V2, Depth Pro, Depth Anything 3, or a
   class of your own. [cli](docs/reference/cli.md#depth-estimators) lists them with their
   weights' licenses. A class filter keeps 8,586 of the 11,868 foregrounds, and
   [generate-a-dataset](docs/how-to/generate-a-dataset.md#1-stage-a--build-the-library) says
   how to turn it off.

4. **Generate sequences.** Stage B composites objects onto a background and writes each
   frame's color, mattes and disparity.

   ```bash
   uv run python -m video_bokeh.scenes.generate \
     --library-root data/library/da2-large --output data/synth \
     --count 4 --frames 80 --size 512 --bokeh --bokeh-strength 16 --flow
   ```

   - `--count` sets how many sequences to attempt, `--frames` how long each is (80 by
     default), and `--size` its square side in pixels (1024 by default).
   - `--bokeh` renders each sequence's bokeh in the same run. `--bokeh-strength` (16) is the
     blur radius in pixels, at a 1024-pixel width, one unit of disparity from the focus.
   - `--layers`, `--flow`, `--flow-back` and `--occlusion` each add a stream.
     [cli](docs/reference/cli.md#video_bokehscenesgenerate--stage-b) has every flag, and
     [dataset-layout](docs/reference/dataset-layout.md#stage-b--a-generated-sequence) every
     stream.

5. **Or train on the fly.** `SequenceStream`, in `video_bokeh.loader`, generates a new
   sequence from the library for every item a training loop asks for and writes nothing to
   disk, so it needs step 3's library, not step 4's sequences. It takes the same frame count,
   size, streams and bokeh strength as step 4. This example trains a small network on it for
   20 steps:

   ```bash
   uv run python -m video_bokeh.loader.example --library-root data/library/da2-large
   ```

   [train-on-the-sequence-stream](docs/how-to/train-on-the-sequence-stream.md) reads its source
   as a template for your own loop, and [loader](docs/reference/loader.md) lists the options.

**The data is for non-commercial research.** MAGICK's images are CC BY-NC 4.0, as its
[project page](https://ryanndagreat.github.io/MAGICK/) states. So are the `da2-large` weights
Stage A uses by default, as [cli](docs/reference/cli.md#depth-estimators) lists. BG-20k is
MIT-licensed under its
[release agreement](https://jizhizili.github.io/files/gfm_datasets_agreements/BG-20k_Dataset_Release_Agreement.pdf).
Papers that use it must cite Li et al., "Bridging Composite and Real: Towards End-to-end Deep
Image Matting", IJCV 2021, and its images' copyright stays with their owners. A dataset built
from them inherits the non-commercial term. The MIT license below covers this repository's code
only.

## License

[MIT](LICENSE)
