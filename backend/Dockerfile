# Built from the repository root, where the workspace's uv.lock is:
#   docker build -t video-bokeh-api -f backend/Dockerfile .
# backend/Dockerfile.dockerignore keeps that context to the files copied below.
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install dependencies (cached layer). --locked installs the versions in uv.lock, and
# fails the build when the lock no longer matches pyproject.toml.
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/
RUN uv sync --locked --package video-bokeh --extra api --no-dev --no-install-project

# Copy application code
COPY backend/src/ backend/src/

# Install the project itself
RUN uv sync --locked --package video-bokeh --extra api --no-dev

# The API runs from backend/, as it does outside the container.
WORKDIR /app/backend

EXPOSE 8000

# Run the venv's uvicorn directly rather than through `uv run`. `uv run` re-resolves
# and re-syncs the environment at every container start, and it includes the dev group
# by default -- so the image built with --no-dev was downloading ruff, ty, matplotlib
# and 49 other packages on each fresh start: 14.7 s, and a hard dependency on the
# container having network.
CMD ["/app/.venv/bin/uvicorn", "video_bokeh.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
