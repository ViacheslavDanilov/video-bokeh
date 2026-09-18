# 🐍 Video Bokeh Backend

FastAPI backend and dataset pipeline for the depth-aware synthetic bokeh video project.

## 📁 Structure

```
backend/src/video_bokeh/
├── __init__.py
├── api/            main.py                          — FastAPI app
├── acquire/        magick.py  bg20k.py  classify.py  — source pools
├── bridge/         any_to_bokeh.py                   — hand-off to the vendored checkout
├── core/           _collision.py  _fusion.py  _library.py  _metadata.py
│                   _seq_io.py  _sequence_geometry.py  _streams.py  _trajectory.py
├── library/        build.py  _device.py  _neutral_bg.py  _propagation.py  depth/
├── preview/        pack.py                           — streams a human looks at
└── scenes/         generate.py  _compositor.py       — Stage B
```

## 🚀 Quick Start

| You want to | Install |
|---|---|
| generate scenes from an existing library | `uv sync --no-dev` |
| build a library yourself (needs a GPU) | `uv sync --no-dev --extra library` |
| download the source pools | `uv sync --extra acquire` |
| run the API | `uv sync --extra api` |
| develop on the repository | `uv sync --all-extras --dev` |

### Smoke test

`data/library_dev` is tracked in the repository, so this runs right after cloning — no
downloads, no GPU. On the machine this was measured on, 4 sequences of 80 frames took 17.7 s:

```bash
uv run python -m video_bokeh.scenes.generate \
  --library-root data/library_dev --output data/synth_dev \
  --count 4 --frames 80 --size 512 --seed 0
```

Full recipes — building a library, downloading the source pools — are in
[`docs/how-to/generate-a-dataset.md`](../docs/how-to/generate-a-dataset.md). Every flag is in
[`docs/reference/cli.md`](../docs/reference/cli.md). The on-disk contract each stage writes is
in [`docs/reference/dataset-layout.md`](../docs/reference/dataset-layout.md).

**`--extra acquire` is not a light install.** It pulls in `open-clip-torch`, which pulls in
`torch`, despite what "acquire" suggests. The runnable download commands live in `AGENTS.md`;
two facts worth knowing before you run them: the full MAGICK mirror comes from the HuggingFace
CLI, not this repository's script, and the BG-20k Kaggle download lands as upload shards
`1/`…`7/` that have to be concatenated into the full `train/` and `testval/` split.

### Run the API

```bash
uv run uvicorn video_bokeh.api.main:app --reload --port 8000
```

- API: http://localhost:8000
- Docs: http://localhost:8000/docs

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
|--------|----------|--------------|
| GET | `/health` | Health check |
