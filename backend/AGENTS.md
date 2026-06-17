# Backend — Agent Guide

FastAPI on Python 3.13, managed with `uv`. Type checker: `ty` (astral). Linter/formatter: `ruff`. Tests: `pytest`. Root rules in `../AGENTS.md` still apply.

## Toolchain

- **Python 3.13 only.** `requires-python = ">=3.13"` in `pyproject.toml`. Don't downgrade syntax for older versions.
- **`uv` is the package manager** — not pip, not poetry, not conda. Lockfile is `../uv.lock` (at repo root because this is a uv workspace; `[tool.uv.workspace] members = ["backend"]`).
- **All Python commands go through `uv run ...`** so they use the locked environment.

## Commands

Run from `backend/` unless noted.

| Task | Command |
|---|---|
| Install (dev deps included) | `uv sync --dev` (from repo root) |
| Run API (reload) | `uv run uvicorn video_bokeh.main:app --reload --port 8000` |
| Tests | `uv run pytest` |
| Type check | `uv run ty check src/` |
| Lint | `uv run ruff check src/` |
| Format | `uv run ruff format src/` |
| Pre-commit (all hooks) | `uv run pre-commit run --all-files` (from repo root) |
| Add dep | `uv add <pkg> --package video-bokeh` |
| Add dev dep | `uv add <pkg> --package video-bokeh --dev` |
| Remove dep | `uv remove <pkg> --package video-bokeh` |

Pre-commit invokes `pycln`, `ruff` (with `--fix`), `ruff-format`, and `ty` against `backend/src`. Config flags live in `backend/pyproject.toml`; runner config is `../.pre-commit-config.yaml`.

## Structure

```
backend/
├── src/
│   ├── video_bokeh/   # FastAPI runtime (the package shipped in the wheel)
│   └── data/          # Dataset download + preprocessing scripts
├── tests/             # pytest tests
├── models/            # Trained model artifacts (gitignored)
├── data/              # Datasets (gitignored)
├── third_party/       # Git submodules — DO NOT MODIFY
└── pyproject.toml
```

- **`src/video_bokeh/`** = production code (API surface).
- **`src/data/`** = standalone scripts, run as modules from `backend/`: `uv run python -m data.download_magick ...`.
- **`third_party/`** = git submodules. Read-only. To update: `git submodule update --remote <path>` after confirming with the user.

## Conventions

- **Ruff config** is in `backend/pyproject.toml` (`[tool.ruff]`). Line length 88, target `py313`. Lint selection includes pyflakes, isort, bugbear, comprehensions, pyupgrade — don't reintroduce things ruff would remove.
- **isort first-party packages** are `video_bokeh` and `data` (configured). Local imports follow the third-party block.
- **Type hints required on public functions.** `ty` runs in pre-commit against `src/`. Tests are excluded.
- **`models/` and `data/` are excluded from pre-commit** (see top-level `.pre-commit-config.yaml`). Don't add Python files there.
- **No emoji in code or commit messages** unless the user explicitly asks. (README files can use them — they already do.)

## Datasets

Dataset scripts assume working directory is `backend/`. Examples:

```bash
# 1. Acquire sources
#    MAGICK dev mirror (HuggingFace)
uv run python -m data.download_magick \
  --metadata data/magick_metadata.csv \
  --output   data/magick_dev \
  --count    20 --seed 0
#    BG-20k full archive (Kaggle) — needs ~/.kaggle/kaggle.json
uv run python -m data.download_bg20k --output data/bg-20k

# 2. Stage A — build the artifact library (depth runs once per asset)
uv run python -m data.build_library \
  --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
  --output data/library_dev --size 1024 --model da2-large

# 3. Stage B — generate sequences on the fly from the library
uv run python -m data.generate_dataset \
  --library-root data/library_dev --output data/synth_dev \
  --count 10 --frames 80 --size 1024 --seed 0

# 4. Bridge to any-to-bokeh inference
uv run python -m data.prepare_any_to_bokeh --data-root data/synth_dev
```

`backend/data/` is gitignored — outputs stay local.

## Verification before claiming done

- Run `uv run pre-commit run --all-files` before reporting work as complete. CI runs the same hooks.
- For API changes, hit the endpoint (`curl` or `/docs`) — type-check doesn't verify behavior.
- For dataset scripts, run them against a small `--count` and confirm the output layout matches what the script claims.
