# any-to-bokeh's environment, for Stage C with VIDEO_BOKEH_RUNNER=docker. Built from the
# repository root:
#   docker build -t video-bokeh-a2b -f backend/docker/any-to-bokeh/Dockerfile .
# Code and weights are not in it: the repository, its checkpoints and the Hugging Face cache
# are mounted at run time, so the image holds the dependencies alone. The pins match
# scripts/setup_third_party.sh.
FROM python:3.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# opencv-python needs libGL and GLib even when nothing is displayed, and noise has no
# wheel, so it builds from source.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

# 2.7 is the first torch with kernels for Blackwell cards such as the RTX 5090.
RUN uv pip install --system --no-cache \
    torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 \
    --index-url https://download.pytorch.org/whl/cu128

COPY backend/third_party/any-to-bokeh/requirements.txt /tmp/requirements.txt
RUN uv pip install --system --no-cache -r /tmp/requirements.txt
