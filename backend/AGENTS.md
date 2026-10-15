# Backend — Agent Guide

FastAPI on Python 3.13, managed with `uv`. Type checker: `ty` (astral). Linter/formatter: `ruff`. Tests: `pytest`. Root rules in `../AGENTS.md` still apply.

## Toolchain

- **Python 3.13 only.** `requires-python = ">=3.13"` in `pyproject.toml`. Don't downgrade syntax for older versions.
  - One exception: `src/video_bokeh/library/depth/_da3_worker.py` runs under Depth Anything 3's own Python 3.12, so it stays compatible with that. `pyproject.toml` gives ruff a `py312` target for that file alone.
- **Models that cannot share our environment run in their own.** `VIDEO_BOKEH_RUNNER=docker`, the default of `make` and `scripts/lab_run.sh` on Linux with Docker's NVIDIA runtime, runs each in the image its class names in `docker_image`, built from `docker/` by `make images`; `local`, the default elsewhere, runs them in their venvs or in this process. `core/_worker.py`'s `runner` reads the variable and `model_command` builds the command; the Makefile and `lab_run.sh` only pick the default. Tests reset the variable, so a shell export cannot change them.
- **`uv` is the package manager** — not pip, not poetry, not conda. Lockfile is `../uv.lock` (at repo root because this is a uv workspace; `[tool.uv.workspace] members = ["backend"]`).
- **All Python commands go through `uv run ...`** so they use the locked environment.

## Commands

Run from `backend/` unless noted.

| Task | Command |
|---|---|
| Install everything (development) | `uv sync --all-extras --dev` (from repo root) |
| Install Stage B only | `uv sync --no-dev` (from repo root) |
| Install Stage A | `uv sync --no-dev --extra library` |
| Install the training loader | `uv sync --no-dev --extra loader` |
| Install Stage C | `uv sync --no-dev --extra render` |
| Run API (reload) | `uv run uvicorn video_bokeh.api.main:app --reload --port 8000` |
| Tests | `uv run pytest` |
| Type check | `uv run ty check src/` |
| Lint | `uv run ruff check src/` |
| Format | `uv run ruff format src/` |
| Pre-commit (all hooks) | `uv run pre-commit run --all-files` (from repo root) |
| Add a base dep | `uv add <pkg> --package video-bokeh` |
| Add a role dep | `uv add <pkg> --package video-bokeh --optional <role>` |
| Add a dev dep | `uv add <pkg> --package video-bokeh --dev` |
| Remove dep | `uv remove <pkg> --package video-bokeh` |

Pre-commit invokes `ruff` (with `--fix`), `ruff-format`, and `ty` against `backend/src`. Config flags live in `backend/pyproject.toml`; runner config is `../.pre-commit-config.yaml`.

## Structure

```
backend/
├── src/
│   └── video_bokeh/   # FastAPI runtime and dataset pipeline (the package shipped in the wheel)
├── tests/             # pytest tests
├── data/              # Datasets (gitignored)
├── docker/            # The Dockerfile of the model that cannot share our environment, built by `make images`
├── envs/              # Venvs for models that cannot share ours, built by ../scripts/ (gitignored)
└── pyproject.toml
```

- **`src/video_bokeh/`** = production code (FastAPI runtime and dataset pipeline).

## Conventions

- **Ruff config** is in `backend/pyproject.toml` (`[tool.ruff]`). Line length 88, target `py313`. Lint selection includes pyflakes, isort, bugbear, comprehensions, pyupgrade — don't reintroduce things ruff would remove.
- **isort first-party package** is `video_bokeh` (configured). Local imports follow the third-party block.
- **Type hints required on public functions.** `ty` runs in pre-commit against `src/`. Tests are excluded.
- **`data/` is excluded from pre-commit** (see top-level `.pre-commit-config.yaml`). Don't add Python files there.
- **No emoji in code or commit messages** unless the user explicitly asks. (README files can use them — they already do.)

## Datasets

Dataset scripts assume working directory is `backend/`. Examples:

```bash
# 1. Acquire sources
#    MAGICK dev pool (HuggingFace), then CLIP predictions for what it lacks
uv run python -m video_bokeh.acquire.magick \
  --metadata data/magick_metadata.csv \
  --output   data/magick_dev \
  --count    30 --seed 11
uv run python -m video_bokeh.acquire.classify --data-root data/magick_dev --keep-existing \
  --num-workers 0
#    BG-20k dev pool, one file at a time (Kaggle) — needs ~/.kaggle/kaggle.json
uv run python -m video_bokeh.acquire.bg20k --output data/bg-20k_dev --count 30 --seed 11
#    BG-20k full archive
uv run python -m video_bokeh.acquire.bg20k --output data/bg-20k

# 2. Stage A — build the artifact library (depth runs once per asset)
uv run python -m video_bokeh.library.build \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output data/library_dev/da2-large --size 1024 --model da2-large

# 3. Stage B — generate sequences on the fly from the library
#    Writes all_in_focus/*.png (RGB), alpha/*.tif (one page per object)
#    and disparity/*.png (uint16), and with --layers the layers/ stream the
#    layered renderer needs. --bokeh renders each sequence's bokeh in the same
#    run, from the layers in memory, and --flow writes its exact optical flow.
#    Each run rewrites manifest.csv (sequences and background ids), objects.csv
#    (object trajectories and fallbacks), and run.json (settings and provenance).
#    See docs/reference/dataset-layout.md.
uv run python -m video_bokeh.scenes.generate \
  --library-root data/library_dev/da2-large --output data/synth_dev \
  --count 10 --frames 80 --size 1024 --seed 0 --n-objects-max 5 --layers

# 4. Stage C — render bokeh again into each sequence's bokeh/, over sequences written
#    with --layers, at another strength or focus than --bokeh rendered in the same run.
uv run --extra render python -m video_bokeh.render.run --data-root data/synth_dev \
  --strength 24
```

`backend/data/` is gitignored — outputs stay local.

## Verification before claiming done

- Run `uv run pre-commit run --all-files` before reporting work as complete. CI runs the same hooks.
- For API changes, hit the endpoint (`curl` or `/docs`) — type-check doesn't verify behavior.
- For dataset scripts, run them against a small `--count` and confirm the output layout matches what the script claims.
