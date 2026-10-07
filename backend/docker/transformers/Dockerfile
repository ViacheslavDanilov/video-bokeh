# The environment of the depth estimators served through Hugging Face transformers, for
# VIDEO_BOKEH_RUNNER=docker. Built from the repository root, once per family:
#   docker build -t video-bokeh-da2 -f backend/docker/transformers/Dockerfile .
#   docker build -t video-bokeh-depth-pro -f backend/docker/transformers/Dockerfile .
# Depth Anything V2 and Depth Pro need the same packages today, so they share this recipe
# under two names; either can take its own pins without touching the other. The worker
# script and the weights are not in it: the repository and the Hugging Face cache are
# mounted at run time. The versions are uv.lock's, so the image computes what the backend
# does in process.
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

RUN uv pip install --system --no-cache \
    torch==2.11.0 torchvision==0.26.0 transformers==5.6.2 \
    numpy==2.4.4 pillow==12.2.0 huggingface-hub==1.11.0 safetensors==0.7.0 \
    tokenizers==0.22.2
