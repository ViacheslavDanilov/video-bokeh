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

- **Depth-aware bokeh** – Apply DSLR-style shallow-focus blur guided by estimated depth maps.
- **Modular pipeline** – Separate components for depth prediction, blur synthesis, and temporal consistency.
- **Web UI** – Next.js frontend for uploading clips, tuning parameters, and previewing results.

## How It Works

The backend estimates per-frame depth, applies a controllable blur kernel modulated by depth, and returns the composited frames. The frontend exposes parameters (focal plane, blur strength) and streams the rendered output.

## Tech Stack

| Category | Technologies |
|----------|-------------|
| Backend | Python 3.13, FastAPI, Uvicorn |
| Frontend | TypeScript, Next.js, React, Tailwind CSS |
| Data | NumPy, Pillow, tifffile, matplotlib |
| Package Management | uv (backend), pnpm (frontend) |
| Build & CI | Docker, Docker Compose, GitHub Actions |

## Getting Started

### Prerequisites

- Python 3.13+ / [uv](https://docs.astral.sh/uv/)
- Node.js 24+ / [pnpm](https://pnpm.io/)

### Installation & Running

```bash
make setup    # every backend extra, the frontend packages, Chromium for the smoke test
make api      # terminal 1: the API on :8000
make web      # terminal 2: the page on :3000
```

Open [http://localhost:3000](http://localhost:3000) (frontend) and [http://localhost:8000/docs](http://localhost:8000/docs) (API docs).
`make` alone lists every target, including `make check` and `make smoke`.

The page sets the sequence parameters, generates, and compares the streams side by side. It
needs an artifact library behind it: `make api` serves `backend/data/library_dev` from the
main checkout, and `make api LIBRARY=<path>` serves another. Building one with Stage A is in
[backend/README.md](backend/README.md), the page is in
[frontend/README.md](frontend/README.md), and the endpoints are in
[docs/reference/api.md](docs/reference/api.md).

### With Docker

```bash
cp .env.example .env          # then point VIDEO_BOKEH_LIBRARY at a library you built
docker compose up api
```

The containers are `video-bokeh-api` and `video-bokeh-web`. `api` mounts the library read-only
at `/data/library` and writes sequences to `/data/sequences`; both come from
`VIDEO_BOKEH_DATA_ROOT`, which defaults to `backend/data`. Generating a sequence in the container
costs roughly half again what it costs natively — the numbers are in
[docs/reference/api.md](docs/reference/api.md).

To generate training data instead of running the API, see [backend/README.md](backend/README.md).

## License

[MIT](LICENSE)
