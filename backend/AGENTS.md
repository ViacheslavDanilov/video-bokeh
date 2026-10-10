# Backend — Agent Guide

FastAPI on Python 3.13, managed with `uv`. Type checker: `ty` (astral). Linter/formatter: `ruff`. Tests: `pytest`. Root rules in `../AGENTS.md` still apply.

## Toolchain

- **Python 3.13 only.** `requires-python = ">=3.13"` in `pyproject.toml`. Don't downgrade syntax for older versions.
  - Two exceptions: `src/video_bokeh/library/depth/_da3_worker.py` runs under Depth Anything 3's own Python 3.12, and `src/video_bokeh/render/_a2b_launch.py` under any-to-bokeh's Python 3.10, so they stay compatible with those. `pyproject.toml` gives ruff a `py312` and a `py310` target for those files alone.
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
| Run API (reload) | `VIDEO_BOKEH_LIBRARY=data/library_dev uv run uvicorn video_bokeh.api.main:app --reload --port 8000` |
| Tests | `uv run pytest` |
| Type check | `uv run ty check src/` |
| Lint | `uv run ruff check src/` |
| Format | `uv run ruff format src/` |
| Pre-commit (all hooks) | `uv run pre-commit run --all-files` (from repo root) |
| Add a base dep | `uv add <pkg> --package video-bokeh` |
| Add a role dep | `uv add <pkg> --package video-bokeh --optional <role>` |
| Add a dev dep | `uv add <pkg> --package video-bokeh --dev` |
| Remove dep | `uv remove <pkg> --package video-bokeh` |

Pre-commit invokes `pycln`, `ruff` (with `--fix`), `ruff-format`, and `ty` against `backend/src`. Config flags live in `backend/pyproject.toml`; runner config is `../.pre-commit-config.yaml`.

## Structure

```
backend/
├── src/
│   └── video_bokeh/   # FastAPI runtime and dataset pipeline (the package shipped in the wheel)
├── tests/             # pytest tests
├── models/            # Trained model artifacts (gitignored)
├── data/              # Datasets (gitignored)
├── docker/            # One Dockerfile per model family, built by `make images`
├── envs/              # Venvs for models that cannot share ours, built by ../scripts/ (gitignored)
├── third_party/       # Git submodules — DO NOT MODIFY
└── pyproject.toml
```

- **`src/video_bokeh/`** = production code (FastAPI runtime and dataset pipeline).
- **`third_party/`** = git submodules. Read-only. To update: `git submodule update --remote <path>` after confirming with the user.

## Conventions

- **Ruff config** is in `backend/pyproject.toml` (`[tool.ruff]`). Line length 88, target `py313`. Lint selection includes pyflakes, isort, bugbear, comprehensions, pyupgrade — don't reintroduce things ruff would remove.
- **isort first-party package** is `video_bokeh` (configured). Local imports follow the third-party block.
- **Type hints required on public functions.** `ty` runs in pre-commit against `src/`. Tests are excluded.
- **`models/` and `data/` are excluded from pre-commit** (see top-level `.pre-commit-config.yaml`). Don't add Python files there.
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
  --output data/library_dev --size 1024 --model da2-large

# 3. Stage B — generate sequences on the fly from the library
#    Writes all_in_focus/*.png (RGB), alpha/*.tif (one page per object)
#    and disparity/*.png (uint16), and with --layers the layers/ stream the
#    layered renderer needs. --bokeh renders each sequence's bokeh in the same
#    run, from the layers in memory. See docs/reference/dataset-layout.md.
uv run python -m video_bokeh.scenes.generate \
  --library-root data/library_dev --output data/synth_dev \
  --count 10 --frames 80 --size 1024 --seed 0 --n-objects-max 5 --layers

# 4. Stage C — render bokeh into each sequence's bokeh/. layered, the default, runs
#    anywhere, over sequences written with --layers. any-to-bokeh is for comparison: NVIDIA
#    only, offline, and needs scripts/setup_third_party.sh first (first run on an RTX 5090
#    on 2026-10-07)
uv run --extra render python -m video_bokeh.render.run --data-root data/synth_dev
uv run --extra render python -m video_bokeh.render.run --data-root data/synth_dev \
  --renderer any-to-bokeh

# Or only convert for any-to-bokeh, to inspect its inputs
uv run python -m video_bokeh.bridge.any_to_bokeh --data-root data/synth_dev
```

`backend/data/` is gitignored — outputs stay local.

## Verification before claiming done

- Run `uv run pre-commit run --all-files` before reporting work as complete. CI runs the same hooks.
- For API changes, hit the endpoint (`curl` or `/docs`) — type-check doesn't verify behavior.
- For dataset scripts, run them against a small `--count` and confirm the output layout matches what the script claims.
