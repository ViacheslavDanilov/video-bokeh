# Backend: Agent Guide

FastAPI on Python 3.13, managed with `uv`. Type checker: `ty` (astral). Linter/formatter: `ruff`. Tests: `pytest`. Root rules in `../AGENTS.md` still apply.

## Toolchain

- **Python 3.13 only.** `requires-python = ">=3.13"` in `pyproject.toml`. Don't downgrade syntax for older versions.
  - One exception: `src/video_bokeh/library/depth/_da3_worker.py` runs under Depth Anything 3's own Python 3.12, so it stays compatible with that. `pyproject.toml` gives ruff a `py312` target for that file alone.
- **A model that cannot share our environment runs in its own.** Today that is Depth Anything 3 alone; every other model runs in this process. `VIDEO_BOKEH_RUNNER=docker`, the default of `make` on Linux with Docker's NVIDIA runtime, runs such a model in the image its class names in `docker_image`, built from `docker/` by `make images`; `local`, the default elsewhere, runs it in its venv. `core/_worker.py`'s `runner` reads the variable and `model_command` builds the command; the Makefile only picks the default. Tests reset the variable, so a shell export cannot change them.
- **`uv` is the package manager**: not pip, not poetry, not conda. Lockfile is `../uv.lock` (at repo root because this is a uv workspace; `[tool.uv.workspace] members = ["backend"]`).
- **All Python commands go through `uv run ...`** so they use the locked environment.

## Commands

Run from `backend/` unless noted.

| Task | Command |
|---|---|
| Install everything (development) | `uv sync --all-extras --dev` (from repo root) |
| Install Stage B only | `uv sync --no-dev` (from repo root) |
| Install Stage A | `uv sync --no-dev --extra library` |
| Install the training loader | `uv sync --no-dev --extra loader` |
| Install the bokeh re-render (`render.run`) | `uv sync --no-dev --extra render` |
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

## Conventions

- **Ruff config** is in `backend/pyproject.toml` (`[tool.ruff]`). Line length 88, target `py313`. Lint selection includes pyflakes, isort, bugbear, comprehensions, pyupgrade. Don't reintroduce things ruff would remove.
- **isort first-party package** is `video_bokeh` (configured). Local imports follow the third-party block.
- **Type hints required on public functions.** `ty` runs in pre-commit against `src/`. Tests are excluded.
- **`data/` is excluded from pre-commit** (see top-level `.pre-commit-config.yaml`). Don't add Python files there.

## Datasets

Dataset scripts run from `backend/`. [`docs/how-to/generate-a-dataset.md`](../docs/how-to/generate-a-dataset.md) holds every recipe: acquiring the pools, Stage A's library, Stage B's sequences and re-rendering the bokeh. [`docs/reference/cli.md`](../docs/reference/cli.md) lists each module's flags. `backend/data/` is mostly gitignored, so outputs stay local.

## Verification before claiming done

- Run `uv run pre-commit run --all-files` before reporting work as complete. CI runs the same hooks.
- For API changes, hit the endpoint (`curl` or `/docs`): type-check doesn't verify behavior.
- For dataset scripts, run them against a small `--count` and confirm the output layout matches what the script claims.
