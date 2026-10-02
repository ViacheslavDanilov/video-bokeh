# Shortcuts for the commands people and agents run most. Each target is a thin wrapper:
# the tools and their flags are documented in AGENTS.md, backend/AGENTS.md and
# frontend/AGENTS.md. `make` alone lists the targets.

.DEFAULT_GOAL := help
.PHONY: help setup libraries api bokeh web smoke test check

# The libraries live under backend/data/, which is not in git, so a second worktree has
# none of its own. Resolve them against the main checkout, which every worktree shares.
MAIN_CHECKOUT := $(patsubst %/.git,%,$(shell git rev-parse --path-format=absolute --git-common-dir))
# One library, or a directory of them: `make libraries` fills it with one library per
# depth estimator, which is what the page's picker chooses between.
LIBRARY ?= $(MAIN_CHECKOUT)/backend/data/library
ESTIMATORS := da2-large da3-mono-large depth-pro
# Passed to every Stage A build, e.g. "--subjects , --styles , --subject-thr 0" for no
# class filter.
BUILD_FLAGS ?=

help: ## List the targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z]+:.*## / {printf "  make %-9s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Install every backend extra, the frontend and the smoke test's Chromium
	uv sync --all-extras --dev
	cd frontend && pnpm install --frozen-lockfile && pnpm exec playwright install chromium

# Each build writes under a dot-prefixed name the API does not list, and is renamed into
# place only once it succeeds, so an interrupted build is never served and a re-run builds
# only what is missing. An existing library is skipped rather than rebuilt in place: its id
# would stay the same while its pixels changed, and cached sequences would go stale.
libraries: ## Build one library per depth estimator into LIBRARY (da3 needs scripts/setup_depth_anything_3.sh)
	@out="$(abspath $(LIBRARY))"; for estimator in $(ESTIMATORS); do \
	  if [ -d "$$out/$$estimator" ]; then echo "$$estimator: exists, skipped"; continue; fi; \
	  rm -rf "$$out/.$$estimator" && \
	  (cd backend && uv run --extra library python -m video_bokeh.library.build \
	    --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
	    --output "$$out/.$$estimator" --model $$estimator $(BUILD_FLAGS)) && \
	  mv "$$out/.$$estimator" "$$out/$$estimator" || exit 1; \
	done

api: ## Serve the API on :8000 from LIBRARY (default: the main checkout's libraries)
	cd backend && VIDEO_BOKEH_LIBRARY="$(abspath $(LIBRARY))" uv run uvicorn video_bokeh.api.main:app --reload --port 8000

# The data root the API writes sequences under, VIDEO_BOKEH_DATA_ROOT or backend/data as
# make api leaves it, so this renders whatever the page has generated since the last run.
bokeh: ## Render bokeh for the sequences the page generated (NVIDIA only; setup_third_party.sh first)
	cd backend && uv run --extra render python -m video_bokeh.render.run \
	  --data-root "$${VIDEO_BOKEH_DATA_ROOT:-data}" --missing

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
