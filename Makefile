# Shortcuts for the common commands. `make` lists them.

.DEFAULT_GOAL := help
.PHONY: help setup pools libraries images api web smoke test check

# Libraries are not in git, so a second worktree uses the main checkout's.
MAIN_CHECKOUT := $(patsubst %/.git,%,$(shell git rev-parse --path-format=absolute --git-common-dir))
# One library, or a directory holding several, such as one per depth estimator.
LIBRARY ?= $(MAIN_CHECKOUT)/backend/data/library_dev
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

# BG-20k goes first: Kaggle is the source that may refuse, and it would refuse at the first
# request, before MAGICK starts its 11,868 downloads. BG-20k is skipped once its images/
# holds images, after a finished run or a download by hand, because a rerun would fetch its
# whole archive again. MAGICK skips the images it has, so a rerun resumes it.
pools: ## Download the full MAGICK and BG-20k pools into backend/data
	@cd backend && if ls data/bg-20k/images 2> /dev/null | grep -q .; then \
	  echo "bg-20k: data/bg-20k/images holds images, skipped"; \
	elif ! uv run --extra acquire python -m video_bokeh.acquire.bg20k --output data/bg-20k; then \
	  echo "error: BG-20k did not download. If Kaggle refused it, put your Kaggle API key in" >&2; \
	  echo "~/.kaggle/kaggle.json and run make pools again. Or download BG-20k by hand into" >&2; \
	  echo "backend/data/bg-20k/images/train and images/testval; make pools then skips it." >&2; \
	  exit 1; \
	fi
	cd backend && uv run --extra acquire python -m video_bokeh.acquire.magick \
	  --metadata data/magick/metadata.csv --output data/magick --count 11868

# Builds under a hidden name and renames when done, so a half-built library is never
# served. An existing library is skipped, so cached sequences stay valid.
libraries: ## Build one dev library per depth estimator into LIBRARY
	@out="$(abspath $(LIBRARY))"; for estimator in $(ESTIMATORS); do \
	  if [ -d "$$out/$$estimator" ]; then echo "$$estimator: exists, skipped"; continue; fi; \
	  rm -rf "$$out/.$$estimator" && \
	  (cd backend && VIDEO_BOKEH_RUNNER=$(RUNNER) uv run --extra library python -m video_bokeh.library.build \
	    --fg-data-root data/magick_dev --bg-data-root data/bg-20k_dev \
	    --output "$$out/.$$estimator" --model $$estimator $(BUILD_FLAGS)) && \
	  mv "$$out/.$$estimator" "$$out/$$estimator" || exit 1; \
	done

images: ## Build Depth Anything 3's Docker image (NVIDIA only)
	docker build -t video-bokeh-da3 -f backend/docker/depth-anything-3/Dockerfile .

api: ## Serve the API on :8000 from LIBRARY
	cd backend && VIDEO_BOKEH_LIBRARY="$(abspath $(LIBRARY))" uv run uvicorn video_bokeh.api.main:app --reload --port 8000

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
