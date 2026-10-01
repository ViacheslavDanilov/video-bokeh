#!/usr/bin/env bash
# Set up the environment the da3-* depth estimators run in.
#
# Depth Anything 3 cannot share the backend environment: it pins numpy<2, its
# requires-python stops before Python 3.13.1, and it depends on xformers, which has no
# macOS wheel. So it gets its own Python 3.12 venv, and video_bokeh drives it through a
# worker process (backend/src/video_bokeh/library/depth/_da3_worker.py).
#
# What this does:
#   1. Creates a Python 3.12 venv at backend/envs/depth-anything-3/.venv via uv.
#   2. Installs Depth Anything 3's declared dependencies except three:
#      - xformers, which inference does not need, and which has no macOS wheel;
#      - pycolmap, which only the COLMAP export uses and which ships a second OpenMP
#        runtime that aborts the process next to torch's. The worker stubs it;
#      - pre-commit, a development tool of that repository.
#      Adds addict, which the package imports without declaring. Pins torch and
#      torchvision to the versions this was tested with, 2.14.0 and 0.29.0.
#   3. Installs depth-anything-3 0.1.1 itself with --no-deps, and checks it imports.
#
# The weights (depth-anything/DA3MONO-LARGE, 1.34 GB) download from Hugging Face on
# first use, into $HF_HOME.
#
# Usage: scripts/setup_depth_anything_3.sh   (idempotent)

set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
VENV="$REPO_ROOT/backend/envs/depth-anything-3/.venv"
PY="$VENV/bin/python"

if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv not found on PATH. Install from https://docs.astral.sh/uv/" >&2
    exit 1
fi

if [[ -x "$PY" ]]; then
    echo "[1/3] Reusing existing venv at $VENV"
else
    echo "[1/3] Creating venv at $VENV (Python 3.12)"
    uv venv --python 3.12 "$VENV"
fi

echo "[2/3] Installing dependencies"
uv pip install --python "$PY" \
    addict e3nn einops evo fastapi huggingface-hub imageio "moviepy==1.0.3" "numpy<2" \
    omegaconf open3d opencv-python pillow pillow-heif plyfile requests safetensors \
    "torch==2.14.0" "torchvision==0.29.0" trimesh "typer>=0.9.0" uvicorn

echo "[3/3] Installing depth-anything-3 0.1.1"
uv pip install --python "$PY" --no-deps "depth-anything-3==0.1.1"

"$PY" - <<'PY'
import sys, types
sys.modules.setdefault("pycolmap", types.ModuleType("pycolmap"))
import numpy, torch
from depth_anything_3.api import DepthAnything3  # noqa: F401
print(f"ok: torch {torch.__version__}, numpy {numpy.__version__}")
PY

echo "Done. Use it with: uv run python -m video_bokeh.library.build --model da3-mono-large ..."
