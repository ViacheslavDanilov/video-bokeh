#!/usr/bin/env bash
# Set up the third-party tooling needed for any-to-bokeh inference. CUDA-only;
# intended to run on the server.
#
# What this does:
#   1. Initializes the any-to-bokeh git submodule (idempotent).
#   2. Creates a Python 3.10 venv at backend/third_party/.venv via uv, installs
#      PyTorch 2.4.1 with CUDA 12.4 wheels (any-to-bokeh's requirements.txt
#      does not pin torch), then installs any-to-bokeh's own dependencies.
#   3. Prints the remaining manual step (UNet + VAE weights live on Google
#      Drive and require a browser download).
#
# Usage: scripts/setup_third_party.sh

set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
TP_DIR="$REPO_ROOT/backend/third_party"
VENV="$TP_DIR/.venv"
A2B_DIR="$TP_DIR/any-to-bokeh"

if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv not found on PATH. Install from https://docs.astral.sh/uv/" >&2
    exit 1
fi

# 1. Submodules
echo "[1/3] git submodule update --init --recursive"
git -C "$REPO_ROOT" submodule update --init --recursive

# 2. Venv + deps
if [ ! -d "$VENV" ]; then
    echo "[2/3] Creating venv at $VENV with uv (Python 3.10)"
    uv venv --python 3.10 "$VENV"
else
    echo "[2/3] Reusing existing venv at $VENV"
fi

echo "      Installing PyTorch 2.4.1 with CUDA 12.4 wheels"
echo "      (override CUDA_INDEX_URL for a different CUDA version)"
CUDA_INDEX_URL="${CUDA_INDEX_URL:-https://download.pytorch.org/whl/cu124}"
uv pip install --python "$VENV/bin/python" \
    torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1 \
    --index-url "$CUDA_INDEX_URL"

echo "      Installing any-to-bokeh requirements"
uv pip install --python "$VENV/bin/python" -r "$A2B_DIR/requirements.txt"

# 3. Manual step
cat <<EOF

[3/3] Done.

Activate the third-party venv before running any-to-bokeh:
    source $VENV/bin/activate

Remaining manual step — any-to-bokeh weights are not on Hugging Face:
    1. Download the UNet + VAE checkpoints from Google Drive:
           https://drive.google.com/file/d/11UQcR7-GJtobPNKlF3f-q97xYX9pyEXb/view
    2. Extract under (matches inference_demo.py defaults, gitignored by a2b):
           $A2B_DIR/checkpoints/unet/
           $A2B_DIR/checkpoints/vae/

The Stable Video Diffusion base (stabilityai/stable-video-diffusion-img2vid-xt)
is pulled from HF on first inference; ensure huggingface-cli is logged in if
you've gated that model.
EOF
