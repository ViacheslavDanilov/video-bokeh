# Video Bokeh — Agent Guide

Depth-aware synthetic bokeh pipeline for video. FastAPI backend (Python 3.13, `uv`), Next.js frontend (Node 24, `pnpm`). Two stacks, two toolchains — read the area-specific guide before touching code:

- `backend/AGENTS.md` — Python, uv, ruff, ty, pytest, third-party submodules
- `frontend/AGENTS.md` — Next.js (non-standard), pnpm 11, eslint, prettier

## Git workflow

1. **Never `git push` without explicit user approval.** Stage and commit if asked, but stop at the push step. A `PreToolUse` hook in `.claude/settings.json` blocks pushes — do not attempt to bypass it.
2. **Never `--force-push` to `main`.** Force-push to feature branches only after the user authorizes it.
3. **Do not add `Co-Authored-By: Claude ...` trailers** to commit messages. Plain subject + body only.
4. **Commit message style:** Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`). Imperative subject under 72 chars, body explains *why*. Examples in `git log`.
5. **Pre-commit runs on every commit.** Config is `.pre-commit-config.yaml`. If hooks fail, fix the underlying issue — don't use `--no-verify`.
6. **Don't amend pushed commits** without the user's go-ahead (force-push territory).

## Secrets and data

- `.env` files are gitignored. Never commit them or paste their contents into chat logs.
- `backend/.env.example` is the only template that's checked in.
- Dataset directories under `backend/data/` and model weights under `backend/models/` are gitignored and excluded from pre-commit (see `exclude:` in `.pre-commit-config.yaml`). Don't add files there to git.

## Don't touch

- `backend/third_party/` — git submodules (currently `any-to-bokeh`). Treat as read-only vendored code.
- `backend/models/`, `backend/data/` — large binary artifacts, gitignored.
- `frontend/.next/`, `frontend/node_modules/`, `.venv/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/` — generated.

## Verification before claiming done

Run the actual check, don't assume. Type-checking and tests verify correctness of code, not of features — for UI changes, also start the dev server and confirm the behavior in a browser.

| Layer | Command |
|---|---|
| Pre-commit (all hooks) | `uv run pre-commit run --all-files` |
| Backend tests | `cd backend && uv run pytest` |
| Backend types | `cd backend && uv run ty check src/` |
| Backend lint | `cd backend && uv run ruff check src/` |
| Frontend lint | `cd frontend && pnpm lint` |
| Frontend format check | `cd frontend && pnpm check` |
| Frontend build | `cd frontend && pnpm build` |
| Docker build | `docker build -t video-bokeh-backend ./backend` / `docker build -t video-bokeh-frontend ./frontend` |

CI mirrors these in `.github/workflows/ci.yaml`. If a step passes locally but fails in CI, suspect tool-version drift first (e.g., pnpm `latest` may be newer than your local).

## Where things live

- `backend/src/video_bokeh/` — FastAPI runtime
- `backend/src/data/` — dataset download + preprocessing scripts (run from `backend/`)
- `frontend/src/` — Next.js app
- `vault/` — long-form writeups and reports (see `vault/` writing style if you're editing those)
- `docs/` — design specs and decision records
- `scripts/` — repo-level setup scripts (`setup_third_party.sh`, etc.)
