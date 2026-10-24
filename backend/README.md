# 🐍 Video Bokeh Backend

FastAPI backend and dataset pipeline for the depth-aware synthetic bokeh video project.

## 📁 Structure

```
backend/src/video_bokeh/
├── api/            # HTTP surface
├── acquire/        # Source pools
├── core/           # Geometry, streams, and shared contracts
├── layered/        # Layer-wise bokeh
├── library/        # Stage A
│   └── depth/      # Depth estimators
├── loader/         # On-the-fly training data
├── preview/        # Video packing
├── render/         # Bokeh renderers, and the tool that renders again
└── scenes/         # Stage B
```

## 🚀 Quick Start

| You want to | Install |
|---|---|
| generate sequences from an existing library | `uv sync --no-dev` |
| build a library yourself | `uv sync --no-dev --extra library` |
| download the source pools | `uv sync --no-dev --extra acquire` |
| run the API | `uv sync --no-dev --extra api` |
| encode streams as MP4 to watch them | `uv sync --no-dev --extra preview` |
| train on sequences generated on the fly, or download a library | `uv sync --no-dev --extra loader` |
| render bokeh again for written sequences | `uv sync --no-dev --extra render` |
| develop on the repository | `uv sync --all-extras --dev` |

Drop `--no-dev` and uv adds the `dev` group — pytest, ruff, ty, pre-commit — on top, which
only the last row wants.

### Smoke test

A fresh clone can run the pipeline without a download: the two source
pools `data/magick_dev` (30 foregrounds) and `data/bg-20k_dev` (30 backgrounds) are tracked on
purpose. The artifact library is not — it is generated, and `.gitignore` keeps
`backend/data/library*/` out — so build it once with Stage A, then run Stage B as often as you
like. Both numbers below were measured on an Apple M3 Pro.

**Stage A — build the library.** Install `uv sync --no-dev --extra library`.

```bash
uv run python -m video_bokeh.library.build \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output data/library_dev/da2-small --size 512 --model da2-small
```

**11 s**, on MPS, once the depth model is cached; the first run also pulls it from Hugging
Face. `da2-small` is the fast model and is what makes this a smoke test — `da2-large` is the
default elsewhere and is slower and better. The CLIP filter keeps 17 of the 30 foregrounds.

**Stage B — generate sequences.** `uv sync --no-dev` is enough; Stage B needs no torch.

```bash
uv run python -m video_bokeh.scenes.generate \
  --library-root data/library_dev/da2-small --output data/synth_dev \
  --count 4 --frames 80 --size 512 --seed 0
```

**17 s** for 4 sequences of 80 frames. Rerun it with a different `--seed` or `--count` without
touching Stage A. `--size` need not match the library's: Stage B maps each asset onto the
frame, so a smaller library is only upscaled.

**The bokeh's strength is k**, the blur radius in pixels at a 1024-pixel width, one unit of
disparity from the focus, 16 by default. `--bokeh` renders each sequence's bokeh in the same
run, which needs torch from the `render` or `loader` extra, and `--bokeh-strength` sets k, one
value for the whole run. In Python, `video_bokeh.scenes.generate.generate_dataset` and the training
stream's `SequenceStream` take it as `bokeh_strength`. The API takes `bokeh_strength` in each
request, and the demo has a slider for it.

Full recipes — building a library, downloading the source pools — are in
[`docs/how-to/generate-a-dataset.md`](../docs/how-to/generate-a-dataset.md). Every flag is in
[`docs/reference/cli.md`](../docs/reference/cli.md). The on-disk contract each stage writes is
in [`docs/reference/dataset-layout.md`](../docs/reference/dataset-layout.md). Training straight
from a library, with nothing written, is in
[`docs/reference/loader.md`](../docs/reference/loader.md).

**`--extra acquire` is not a light install.** It pulls in `open-clip-torch`, which pulls in
`torch`, despite what "acquire" suggests. `make pools`, from the repository root, downloads both
full pools. What it runs is in
[`docs/how-to/generate-a-dataset.md`](../docs/how-to/generate-a-dataset.md#full-pools).

### Run the API

The API mounts libraries and generates sequences from the one a request names, on demand. Point
it at one library, or at a directory with one library per subdirectory:

```bash
VIDEO_BOKEH_LIBRARY=data/library_dev/da2-small \
  uv run uvicorn video_bokeh.api.main:app --reload --port 8000
```

- API: http://localhost:8000
- Docs: http://localhost:8000/docs

Without `VIDEO_BOKEH_LIBRARY` it looks for `$VIDEO_BOKEH_DATA_ROOT/library`, and
`VIDEO_BOKEH_DATA_ROOT` itself defaults to `data`. `make libraries`, from the repository
root, writes dev-pool libraries into `data/library_dev/<estimator>`, and `make api` serves
that root by setting `VIDEO_BOKEH_LIBRARY`. Full-pool libraries belong in
`data/library/<estimator>`. Sequences are written under `$VIDEO_BOKEH_DATA_ROOT/sequences/`.

Against `data/library_dev/da2-small`, generate a sequence and watch it:

```bash
curl -X POST http://localhost:8000/sequences \
  -H 'content-type: application/json' \
  -d '{"seed": 42, "frames": 80, "size": 512, "n_objects_min": 4, "n_objects_max": 5}'
```

That takes 8 to 14 seconds on an Apple M3 Pro, or 16 to 25 with its bokeh, and answers with a
sequence id. The same request
again returns the same id in 0.02 s — the id is a hash of the parameters and the library, so
the directory on disk is the cache. Then open
`http://localhost:8000/sequences/<id>/disparity.mp4`.

With several libraries mounted, the request has to name one: add `"library": "<id>"` with an
id from `GET /libraries`. Without it the API answers 422 and lists the ids.

Timings for other frame counts, and for the container, are in `docs/reference/api.md`.

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
# From the repository root, where uv.lock is
docker build -t video-bokeh-api -f backend/Dockerfile .
docker run -p 8000:8000 video-bokeh-api
```

## Development

[The backend agent guide](AGENTS.md#commands) lists the package management, testing,
type-checking, linting, and formatting commands.

## API Endpoints

[The API reference](../docs/reference/api.md) documents the endpoints, request and response
formats, defaults, and measured timings.
