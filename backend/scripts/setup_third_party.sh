#!/usr/bin/env bash
# Set up the third-party tooling needed for video-disparity (VDA) and bokeh
# (any-to-bokeh) generation. CUDA-only; intended to run on the server.
#
# What this does:
#   1. Initializes the VDA + any-to-bokeh git submodules (idempotent).
#   2. Creates a shared Python 3.10 venv at backend/third_party/.venv that
#      satisfies both tools' deps. Both repos hard-pin numpy and torch
#      versions; we install VDA's requirements first, then any-to-bokeh's
#      (whose newer numpy pin wins). Pip will warn about the conflict —
#      ignore unless something breaks at import time.
#   3. Downloads the VDA-Large checkpoint (CC-BY-NC, ~382M params, highest
#      quality) into backend/third_party/Video-Depth-Anything/checkpoints/.
#      Override with VDA_ENCODER=vits|vitb to fetch a smaller variant
#      (vits is Apache-2.0; vitb/vitl are CC-BY-NC).
#   4. Prints the remaining manual step (any-to-bokeh's UNet + VAE weights
#      live on Google Drive and require a browser download).
#
# Usage: backend/scripts/setup_third_party.sh

set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
TP_DIR="$REPO_ROOT/backend/third_party"
VENV="$TP_DIR/.venv"
VDA_DIR="$TP_DIR/Video-Depth-Anything"
A2B_DIR="$TP_DIR/any-to-bokeh"
VDA_CHECKPOINTS="$VDA_DIR/checkpoints"

# Encoder variant: vits (Apache-2.0, 28M), vitb (CC-BY-NC, 113M),
# vitl (CC-BY-NC, 382M, highest quality, default).
VDA_ENCODER="${VDA_ENCODER:-vitl}"
case "$VDA_ENCODER" in
    vits) VDA_HF_REPO="Video-Depth-Anything-Small" ;;
    vitb) VDA_HF_REPO="Video-Depth-Anything-Base" ;;
    vitl) VDA_HF_REPO="Video-Depth-Anything-Large" ;;
    *) echo "error: VDA_ENCODER must be vits|vitb|vitl, got '$VDA_ENCODER'" >&2; exit 1 ;;
esac
VDA_CKPT_NAME="video_depth_anything_${VDA_ENCODER}.pth"
VDA_CKPT_URL="https://huggingface.co/depth-anything/${VDA_HF_REPO}/resolve/main/${VDA_CKPT_NAME}"

# 1. Submodules
echo "[1/4] git submodule update --init --recursive"
git -C "$REPO_ROOT" submodule update --init --recursive

# 2. Shared venv
PY_BIN="${PYTHON:-python3.10}"
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
    echo "error: $PY_BIN not found on PATH. Install Python 3.10 (matches VDA + any-to-bokeh) or"
    echo "       set PYTHON=<path-to-python3.10> and retry." >&2
    exit 1
fi

if [ ! -d "$VENV" ]; then
    echo "[2/4] Creating venv at $VENV using $PY_BIN"
    "$PY_BIN" -m venv "$VENV"
else
    echo "[2/4] Reusing existing venv at $VENV"
fi

# shellcheck source=/dev/null
source "$VENV/bin/activate"
python -m pip install --upgrade pip

echo "      Installing VDA requirements"
pip install -r "$VDA_DIR/requirements.txt"

echo "      Installing any-to-bokeh requirements"
pip install -r "$A2B_DIR/requirements.txt"

# 3. VDA checkpoint (encoder selected via VDA_ENCODER env var)
echo "[3/4] VDA-${VDA_ENCODER} checkpoint"
mkdir -p "$VDA_CHECKPOINTS"
if [ ! -f "$VDA_CHECKPOINTS/$VDA_CKPT_NAME" ]; then
    echo "      Downloading $VDA_CKPT_URL"
    if command -v wget >/dev/null 2>&1; then
        wget -q --show-progress -O "$VDA_CHECKPOINTS/$VDA_CKPT_NAME" "$VDA_CKPT_URL"
    else
        curl -L -o "$VDA_CHECKPOINTS/$VDA_CKPT_NAME" "$VDA_CKPT_URL"
    fi
else
    echo "      Already present: $VDA_CHECKPOINTS/$VDA_CKPT_NAME"
fi

# 4. Manual step
cat <<EOF

[4/4] Done.

Activate the third-party venv before running VDA / bokeh scripts:
    source $VENV/bin/activate

Remaining manual step — any-to-bokeh weights are not on Hugging Face:
    1. Follow $A2B_DIR/README.md to download the UNet + VAE checkpoints
       from Google Drive.
    2. Place them under:
           $REPO_ROOT/backend/models/any_to_bokeh/unet/
           $REPO_ROOT/backend/models/any_to_bokeh/vae/

The Stable Video Diffusion base (stabilityai/stable-video-diffusion-img2vid-xt)
is pulled from HF on first inference; ensure huggingface-cli is logged in if
you've gated that model.
EOF
