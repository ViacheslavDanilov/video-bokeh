# Depth Anything 3's environment, for the da3-* depth estimators with
# VIDEO_BOKEH_RUNNER=docker. Built from the repository root:
#   docker build -t video-bokeh-da3 -f backend/docker/depth-anything-3/Dockerfile .
# The worker script and the weights are not in it: the repository and the Hugging Face cache
# are mounted at run time. The packages are scripts/setup_depth_anything_3.sh's, which says
# why three declared dependencies are left out.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# opencv-python needs libGL and GLib, and open3d libgomp, even when nothing is displayed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

RUN uv pip install --system --no-cache \
    addict e3nn einops evo fastapi huggingface-hub imageio "moviepy==1.0.3" "numpy<2" \
    omegaconf open3d opencv-python pillow pillow-heif plyfile requests safetensors \
    "torch==2.14.0" "torchvision==0.29.0" trimesh "typer>=0.9.0" uvicorn \
    && uv pip install --system --no-cache --no-deps "depth-anything-3==0.1.1"
