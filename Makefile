# Shortcuts for the commands people and agents run most. Each target is a thin wrapper:
# the tools and their flags are documented in AGENTS.md, backend/AGENTS.md and
# frontend/AGENTS.md. `make` alone lists the targets.

.DEFAULT_GOAL := help
.PHONY: help setup api web smoke test check

# The library lives under backend/data/, which is not in git, so a second worktree has
# none of its own. Resolve it against the main checkout, which every worktree shares.
MAIN_CHECKOUT := $(patsubst %/.git,%,$(shell git rev-parse --path-format=absolute --git-common-dir))
LIBRARY ?= $(MAIN_CHECKOUT)/backend/data/library_dev

help: ## List the targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z]+:.*## / {printf "  make %-6s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Install every backend extra, the frontend and the smoke test's Chromium
	uv sync --all-extras --dev
	cd frontend && pnpm install --frozen-lockfile && pnpm exec playwright install chromium

api: ## Serve the API on :8000 from LIBRARY (default: the main checkout's library_dev)
	cd backend && VIDEO_BOKEH_LIBRARY="$(LIBRARY)" uv run uvicorn video_bokeh.api.main:app --reload --port 8000

web: ## Serve the page on :3000
	cd frontend && pnpm dev

smoke: ## Run the browser smoke test, which starts its own servers
	cd frontend && pnpm e2e

test: ## Run the backend tests
	cd backend && uv run pytest -q

check: ## Run every pre-commit hook, the backend tests, frontend lint and format check
	uv run pre-commit run --all-files
	cd backend && uv run pytest -q
	cd frontend && pnpm lint && pnpm check
