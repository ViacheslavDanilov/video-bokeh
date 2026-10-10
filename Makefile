# Shortcuts for the common commands. `make` lists them.

.DEFAULT_GOAL := help
.PHONY: help setup libraries images api bokeh web smoke test check

# Libraries are not in git, so a second worktree uses the main checkout's.
MAIN_CHECKOUT := $(patsubst %/.git,%,$(shell git rev-parse --path-format=absolute --git-common-dir))
# One library, or a directory holding several, such as one per depth estimator.
LIBRARY ?= $(MAIN_CHECKOUT)/backend/data/library
ESTIMATORS := da2-large da3-mono-large depth-pro
# Where the models run: their Docker images where Linux has docker's NVIDIA runtime, their
# venvs elsewhere, as a Mac's Docker has no GPU to give. VIDEO_BOKEH_RUNNER overrides it.
RUNNER := $(or $(VIDEO_BOKEH_RUNNER),$(shell [ "$$(uname)" = Linux ] && docker info --format '{{json .Runtimes}}' 2> /dev/null | grep -q '"nvidia"' && echo docker || echo local))
# Extra flags for every library build. "--subjects , --styles , --subject-thr 0" turns off
# the class filter.
BUILD_FLAGS ?=

help: ## List the targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z]+:.*## / {printf "  make %-9s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Install the backend, the frontend and the test browser
	uv sync --all-extras --dev
	cd frontend && pnpm install --frozen-lockfile && pnpm exec playwright install chromium

# Builds under a hidden name and renames when done, so a half-built library is never
# served. An existing library is skipped, so cached sequences stay valid.
libraries: ## Build one library per depth estimator into LIBRARY
	@out="$(abspath $(LIBRARY))"; for estimator in $(ESTIMATORS); do \
	  if [ -d "$$out/$$estimator" ]; then echo "$$estimator: exists, skipped"; continue; fi; \
	  rm -rf "$$out/.$$estimator" && \
	  (cd backend && VIDEO_BOKEH_RUNNER=$(RUNNER) uv run --extra library python -m video_bokeh.library.build \
	    --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
	    --output "$$out/.$$estimator" --model $$estimator $(BUILD_FLAGS)) && \
	  mv "$$out/.$$estimator" "$$out/$$estimator" || exit 1; \
	done

images: ## Build the models' Docker images (NVIDIA only)
	docker build -t video-bokeh-a2b -f backend/docker/any-to-bokeh/Dockerfile .
	docker build -t video-bokeh-da3 -f backend/docker/depth-anything-3/Dockerfile .
	docker build -t video-bokeh-da2 -f backend/docker/transformers/Dockerfile .
	docker build -t video-bokeh-depth-pro -f backend/docker/transformers/Dockerfile .

api: ## Serve the API on :8000 from LIBRARY
	cd backend && VIDEO_BOKEH_LIBRARY="$(abspath $(LIBRARY))" uv run uvicorn video_bokeh.api.main:app --reload --port 8000

bokeh: ## Render any-to-bokeh for the page's sequences without bokeh (NVIDIA only)
	cd backend && VIDEO_BOKEH_RUNNER=$(RUNNER) uv run --extra render python -m video_bokeh.render.run \
	  --data-root "$${VIDEO_BOKEH_DATA_ROOT:-data}" --missing

web: ## Serve the page on :3000
	cd frontend && pnpm dev

smoke: ## Run the browser smoke test
	cd frontend && pnpm e2e

test: ## Run the backend tests
	cd backend && uv run pytest -q

check: ## Run pre-commit, backend tests, frontend lint and format check
	uv run pre-commit run --all-files
	cd backend && uv run pytest -q
	cd frontend && pnpm lint && pnpm check
