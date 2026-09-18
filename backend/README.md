# 🐍 Video Bokeh Backend

FastAPI backend for the depth-aware synthetic bokeh video pipeline.

## 📁 Structure

```
backend/
├── Dockerfile                  # Container configuration
├── src/
│   └── video_bokeh/            # Runtime + dataset pipeline (package shipped in the wheel)
│       ├── __init__.py
│       ├── main.py                                   # FastAPI app
│       ├── acquire/       magick.py  bg20k.py  classify.py  # source pools
│       ├── bridge/        any_to_bokeh.py             # hand-off to the vendored checkout
│       ├── core/          shared pipeline modules
│       ├── library/       build.py                    # Stage A
│       ├── preview/       pack.py                     # streams a human looks at
│       └── scenes/        generate.py                 # Stage B
├── models/                     # Trained model artifacts
├── data/                       # Datasets (e.g. magick/, magick_dev/)
└── pyproject.toml              # Package dependencies
```

## 🚀 Quick Start

```bash
# From project root
uv sync                     # Install dependencies

# Run the API
uv run uvicorn video_bokeh.main:app --reload --port 8000
```

- API: http://localhost:8000
- Docs: http://localhost:8000/docs

## 📚 Datasets

All dataset scripts live under `src/video_bokeh/acquire/` and `src/video_bokeh/bridge/`. Run from `backend/`.

### MAGICK (HuggingFace)

Sampled dev-set mirror of [OneOverZero/MAGICK](https://huggingface.co/datasets/OneOverZero/MAGICK):

```bash
uv run python -m video_bokeh.acquire.magick \
  --metadata data/magick_metadata.csv \
  --output   data/magick_dev \
  --count    20 --seed 0
```

For the full mirror, use the HF CLI instead:

```bash
huggingface-cli download OneOverZero/MAGICK \
  --repo-type dataset --local-dir data/magick
```

### BG-20k (Kaggle)

Full archive (~25–30 GB) via `kagglehub`. Requires `~/.kaggle/kaggle.json`:

```bash
uv add kagglehub
uv run python -m video_bokeh.acquire.bg20k --output data/bg-20k
```

Files land under `<output>/datasets/nguyenquocdungk16hl/bg-20o/versions/<N>/`
(folders `1/`…`7/` are Kaggle upload shards — concatenate them for the full
`train/` + `testval/` split).

## 🐳 Docker

```bash
# From backend/ directory
docker build -t video-bokeh-backend .
docker run -p 8000:8000 video-bokeh-backend
```

## 📦 Package Management

```bash
# Add a dependency
uv add <package> --package video-bokeh

# Add a dev dependency
uv add <package> --package video-bokeh --dev

# Remove a dependency
uv remove <package> --package video-bokeh
```

## 🧪 Development

```bash
# Run tests
uv run pytest

# Type checking
uv run ty check src/

# Linting & formatting
uv run ruff check src/
uv run ruff format src/
```

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
