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
| build a library yourself | `uv sync --no-dev --extra library` |
| download the source pools | `uv sync --no-dev --extra acquire` |
| run the API | `uv sync --no-dev --extra api` |
| develop on the repository | `uv sync --all-extras --dev` |

Drop `--no-dev` and uv adds the `dev` group — pytest, ruff, ty, pre-commit — on top, which
only the last row wants.

### Smoke test

A fresh clone can run the pipeline without a download or a Kaggle account: the two source
pools `data/magick_dev` (20 foregrounds) and `data/bg-20k_dev` (20 backgrounds) are tracked on
purpose. The artifact library is not — it is generated, and `.gitignore` keeps
`backend/data/library*/` out — so build it once with Stage A, then run Stage B as often as you
like. Both numbers below were measured on an Apple M3 Pro.

**Stage A — build the library.** Install `uv sync --no-dev --extra library`.

```bash
uv run python -m video_bokeh.library.build \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output data/library_dev --size 512 --model da2-small
```

**10 s**, on MPS, once the depth model is cached; the first run also pulls it from Hugging
Face. `da2-small` is the fast model and is what makes this a smoke test — `da2-large` is the
default elsewhere and is slower and better. The CLIP filter keeps about 12 of the 20
foregrounds.

**Stage B — generate sequences.** `uv sync --no-dev` is enough; Stage B needs no torch.

```bash
uv run python -m video_bokeh.scenes.generate \
  --library-root data/library_dev --output data/synth_dev \
  --count 4 --frames 80 --size 512 --seed 0
```

**17 s** for 4 sequences of 80 frames. Rerun it with a different `--seed` or `--count` without
touching Stage A. `--size` must match between the two stages.

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

`docker compose up` from the repository root is the entry point. It builds this image and the
frontend together, publishes 8000 and 3000, and mounts the data root named by
`VIDEO_BOKEH_DATA_ROOT` — see `compose.yaml` and `.env.example`, both at the root.

```bash
# From the repository root
docker compose up --build
```

To build and run this service on its own:

```bash
# From backend/ directory
docker build -t video-bokeh-api .
docker run -p 8000:8000 video-bokeh-api
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
