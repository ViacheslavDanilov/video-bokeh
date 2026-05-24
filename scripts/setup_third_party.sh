#!/usr/bin/env bash
# Set up the third-party tooling needed for any-to-bokeh inference. CUDA-only;
# intended to run on the server.
#
# What this does:
#   1. Initializes the any-to-bokeh git submodule (idempotent).
#   2. Creates a Python 3.10 venv at backend/third_party/any-to-bokeh/.venv
#      via uv (each third-party tool owns its own venv — no shared env),
#      installs PyTorch 2.4.1 with CUDA 12.4 wheels (any-to-bokeh's
#      requirements.txt does not pin torch), then installs any-to-bokeh's
#      own dependencies.
#   3. Downloads the UNet + VAE checkpoints from Google Drive via `uvx gdown`
#      and extracts them. The archive's top-level dir is `checkpoints/`, so
#      extraction lands them at <a2b>/checkpoints/{unet,vae}/ — matching
#      inference_demo.py defaults.
#   4. Downloads the Stable Video Diffusion base model
#      (stabilityai/stable-video-diffusion-img2vid-xt) from Hugging Face into
#      $HF_HOME. inference_demo.py passes local_files_only=True, so this must
#      be cached before the first run.
#
# Usage: scripts/setup_third_party.sh

set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
TP_DIR="$REPO_ROOT/backend/third_party"
A2B_DIR="$TP_DIR/any-to-bokeh"
VENV="$A2B_DIR/.venv"

if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv not found on PATH. Install from https://docs.astral.sh/uv/" >&2
    exit 1
fi

# 1. Submodules
echo "[1/4] git submodule update --init --recursive"
git -C "$REPO_ROOT" submodule update --init --recursive

# 2. Venv + deps
if [ ! -d "$VENV" ]; then
    echo "[2/4] Creating venv at $VENV with uv (Python 3.10)"
    uv venv --python 3.10 "$VENV"
else
    echo "[2/4] Reusing existing venv at $VENV"
fi

echo "      Installing PyTorch 2.4.1 with CUDA 12.4 wheels"
echo "      (override CUDA_INDEX_URL for a different CUDA version)"
CUDA_INDEX_URL="${CUDA_INDEX_URL:-https://download.pytorch.org/whl/cu124}"
uv pip install --python "$VENV/bin/python" \
    torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1 \
    --index-url "$CUDA_INDEX_URL"

echo "      Installing any-to-bokeh requirements"
uv pip install --python "$VENV/bin/python" -r "$A2B_DIR/requirements.txt"

# 3. Checkpoints — download from Google Drive and extract into $A2B_DIR so the
#    archive's top-level checkpoints/ dir lands as $A2B_DIR/checkpoints/.
CHECKPOINTS="$A2B_DIR/checkpoints"
GDRIVE_FILE_ID="${A2B_CHECKPOINTS_FILE_ID:-11UQcR7-GJtobPNKlF3f-q97xYX9pyEXb}"

if [ -d "$CHECKPOINTS/unet" ] && [ -d "$CHECKPOINTS/vae" ]; then
    echo "[3/4] Checkpoints already present at $CHECKPOINTS — skipping"
else
    echo "[3/4] Downloading any-to-bokeh checkpoints from Google Drive"
    ARCHIVE="$A2B_DIR/_a2b_weights.zip"
    uvx gdown "$GDRIVE_FILE_ID" -O "$ARCHIVE"
    echo "      Extracting"
    unzip -q "$ARCHIVE" -d "$A2B_DIR"
    rm -rf "$A2B_DIR/__MACOSX" "$ARCHIVE"
fi

# 4. SVD base model — inference_demo.py loads this with local_files_only=True,
#    so it must be cached in $HF_HOME before the first run.
SVD_REPO="stabilityai/stable-video-diffusion-img2vid-xt"
SVD_CACHE="${HF_HOME:-$HOME/.cache/huggingface}/hub/models--${SVD_REPO//\//__}"

if [ -d "$SVD_CACHE" ]; then
    echo "[4/4] SVD base model already cached at $SVD_CACHE — skipping"
else
    echo "[4/4] Downloading SVD base model ($SVD_REPO) from Hugging Face (~10 GB, fp16)"
    "$VENV/bin/python" -c "
from diffusers import StableVideoDiffusionPipeline
import torch
StableVideoDiffusionPipeline.from_pretrained(
    '$SVD_REPO',
    torch_dtype=torch.float16,
    variant='fp16',
)
print('SVD base model cached successfully')
"
fi

cat <<EOF

Done.

Activate the any-to-bokeh venv before running inference:
    source $VENV/bin/activate
EOF
