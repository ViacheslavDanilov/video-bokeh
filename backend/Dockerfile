FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install dependencies (cached layer)
COPY pyproject.toml ./
RUN uv sync --extra api --no-install-project

# Copy application code
COPY src/ src/

# Install the project itself
RUN uv sync --extra api

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "video_bokeh.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
