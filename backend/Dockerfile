FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install dependencies (cached layer)
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

# Copy application code
COPY src/ src/

# Install the project itself
RUN uv sync --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "video_bokeh.main:app", "--host", "0.0.0.0", "--port", "8000"]
