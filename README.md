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
| Deployment | Docker, GitHub Actions, Google Artifact Registry |

## Getting Started

### Prerequisites

- Python 3.13+ / [uv](https://docs.astral.sh/uv/)
- Node.js 24+ / [pnpm](https://pnpm.io/)

### Installation & Running

```bash
# Backend
cd backend
cp .env.example .env
uv sync
uv run uvicorn video_bokeh.main:app --reload

# Frontend
cd frontend
pnpm install
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000) (frontend) and [http://localhost:8000/docs](http://localhost:8000/docs) (API docs).

## License

[MIT](LICENSE)
