<div align="center">

<img src=".assets/logo.png" width="100" alt="Video Bokeh Logo">

# Video Bokeh

[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/downloads/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178c6.svg)](https://www.typescriptlang.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black.svg)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

Depth-aware synthetic bokeh pipeline for video, with a FastAPI backend and Next.js frontend.

</div>

## Preview

<p align="center">
<img src=".assets/video-bokeh.png" width="80%" alt="Video Bokeh Preview">
</p>

## Features

- **Synthetic training data with known depth** – Objects composited onto backgrounds at disparities we assign, written as video sequences with one matte per object and 16-bit disparity.
- **Three swappable stages** – Depth (Depth Anything V2, Depth Pro, Depth Anything 3 or your own), sequence generation, and bokeh (any-to-bokeh or your own).
- **Training on the fly** – A PyTorch stream that generates a new sequence for every item.
- **Web demo** – Generate a sequence and compare its streams side by side.

## How It Works

Stage A estimates depth once per asset and stores it as a library. Stage B samples objects, a background and depth trajectories from that library and writes sequences. Stage C renders bokeh from each sequence. The web demo generates sequences on request. [docs/explanation/pipeline-explainer.md](docs/explanation/pipeline-explainer.md) walks through all of it.

## Tech Stack

| Category | Technologies |
|----------|-------------|
| Backend | Python 3.13, FastAPI, Uvicorn |
| Frontend | TypeScript, Next.js, React, Tailwind CSS |
| Data | NumPy, Pillow, tifffile, matplotlib |
| Models | PyTorch and Hugging Face transformers for depth (Stage A), any-to-bokeh for bokeh (Stage C) |
| Package Management | uv (backend), pnpm (frontend) |
| Build & CI | Docker, Docker Compose, GitHub Actions |

## Getting Started

### Prerequisites

- Python 3.13+ / [uv](https://docs.astral.sh/uv/)
- Node.js 24+ / [pnpm](https://pnpm.io/)

### Installation & Running

```bash
make setup                          # every backend extra, the frontend, Chromium for the smoke test
scripts/setup_depth_anything_3.sh   # once: the venv Depth Anything 3 runs in
make libraries                      # once: one library per depth estimator
make api                            # terminal 1: the API on :8000
make web                            # terminal 2: the page on :3000
```

Open [http://localhost:3000](http://localhost:3000) (frontend) and [http://localhost:8000/docs](http://localhost:8000/docs) (API docs).
`make` alone lists every target, including `make check` and `make smoke`.

The page picks a depth estimator, sets the sequence parameters, generates, and compares the
streams side by side. It needs libraries behind it, one per depth estimator: `make libraries`
builds them with Depth Anything V2 Large, Depth Anything 3 Mono-Large and Depth Pro into the
main checkout's `backend/data/library/`, and `make api` serves them. Depth Anything 3 runs in
a venv of its own, which `scripts/setup_depth_anything_3.sh` builds once. `make api
LIBRARY=<path>` serves something else: one library, or a directory of them. Building a library
by hand with Stage A is in [backend/README.md](backend/README.md), the page is in
[frontend/README.md](frontend/README.md), and the endpoints are in
[docs/reference/api.md](docs/reference/api.md).

### With Docker

```bash
cp .env.example .env          # only to serve something other than backend/data/library
docker compose up api
```

The containers are `video-bokeh-api` and `video-bokeh-web`. `api` mounts the libraries
read-only at `/data/library` and writes sequences to `/data/sequences`; both come from
`VIDEO_BOKEH_DATA_ROOT`, which defaults to `backend/data`. Generating a sequence in the container
costs roughly half again what it costs natively — the numbers are in
[docs/reference/api.md](docs/reference/api.md).

To generate training data instead of running the API, see [backend/README.md](backend/README.md).

## License

[MIT](LICENSE)
