# 🐍 Video Bokeh Backend

FastAPI backend for the depth-aware synthetic bokeh video pipeline.

## 📁 Structure

```
backend/
├── Dockerfile                  # Container configuration
├── src/video_bokeh/            # Python package (API code)
│   ├── __init__.py
│   └── main.py                 # FastAPI application
├── scripts/                    # Research/CLI scripts (depth conversion, visualization)
├── models/                     # Trained model artifacts
├── data/                       # Datasets
└── pyproject.toml              # Package dependencies
```

## 🚀 Quick Start

```bash
# From project root
uv sync                     # Install dependencies

# Run the API
uv run uvicorn video_bokeh.main:app --reload --port 8000
```

- API: http://localhost:8000
- Docs: http://localhost:8000/docs

## 🐳 Docker

```bash
# From backend/ directory
docker build -t video-bokeh-backend .
docker run -p 8000:8000 video-bokeh-backend
```

## 📦 Package Management

```bash
# Add a dependency
uv add <package> --package video-bokeh

# Add a dev dependency
uv add <package> --package video-bokeh --dev

# Remove a dependency
uv remove <package> --package video-bokeh
```

## 🧪 Development

```bash
# Run tests
uv run pytest

# Type checking
uv run mypy src/

# Linting & formatting
uv run ruff check src/
uv run ruff format src/
```

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
