#!/usr/bin/env bash
# Build the environment the comparison methods run in, on a machine with an NVIDIA card.
#
# Other methods' code never enters this repository. This script clones a pinned commit of
# each into comparison/third_party/, builds what it needs under comparison/envs/, and leaves
# both ignored by git. Every step skips what is already there, so a second run is cheap.
#
# What it builds, each step marked by a .ready file once it is whole:
#   envs/render         Python 3.12 with torch from the CUDA 12.8 wheels, which an RTX 5090
#                       needs: the methods' own pins (torch 1.8 to 2.4) have no kernels for it.
#   envs/cuda-toolkit   nvcc and the CUDA 12.8 headers, from conda-forge through micromamba,
#                       because the pip wheel of nvcc ships no compiler. Only CUDA extensions
#                       are built with it.
#   third_party/mpib    MPIB's ray tracer (https://github.com/JuewenPeng/MPIB, Apache-2.0), the
#                       generator of its paper's Sec. 3.4, with CuPy to run it. Its weights are
#                       not needed: the ray tracer is not a network.
#   third_party/drbokeh Dr.Bokeh's renderer (https://github.com/ShengCN/DrBokeh-Src) with its
#                       scatter_cuda extension. Its code has no license file: it stays on this
#                       machine and is not redistributed.
#
# It is for a Linux x86-64 machine with an NVIDIA driver, g++ and GNU sed, and stops early
# without a driver. A step that fails leaves no marker, so the next run does it again.
#
# Usage: comparison/setup.sh drbokeh | mpib

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ENVS="$HERE/envs"
TP="$HERE/third_party"
TOOLS="$HERE/tools"
RENDER="$ENVS/render"
TOOLKIT="$ENVS/cuda-toolkit"

MPIB_URL="https://github.com/JuewenPeng/MPIB.git"
MPIB_SHA="d77d93dd29b9ae75bcd18b3b70d89d715c1b56f8"

DRBOKEH_URL="https://github.com/ShengCN/DrBokeh-Src.git"
DRBOKEH_SHA="24d96e4fb76a698494e86835c84a7c45ae2ebc10"

command -v uv > /dev/null || { echo "error: uv not found on PATH" >&2; exit 1; }
command -v nvidia-smi > /dev/null || { echo "error: no NVIDIA driver on this machine" >&2; exit 1; }

# Versions the recipe was tested with, on 2026-10-15.
TORCH="torch==2.11.0 torchvision==0.26.0"

render_env() {
    if [ ! -f "$RENDER/.ready" ]; then
        echo "[render] Python 3.12 environment"
        rm -rf "$RENDER"
        uv venv --python 3.12 "$RENDER"
        # shellcheck disable=SC2086
        uv pip install --python "$RENDER/bin/python" $TORCH \
            --index-url https://download.pytorch.org/whl/cu128
        uv pip install --python "$RENDER/bin/python" numpy "pillow<13" matplotlib tqdm \
            scipy tifffile imagecodecs ninja setuptools
        touch "$RENDER/.ready"
    else
        echo "[render] exists, skipped"
    fi
}

cuda_toolkit() {
    if [ ! -f "$TOOLKIT/.ready" ]; then
        rm -rf "$TOOLKIT"
        echo "[cuda-toolkit] nvcc 12.8 through micromamba"
        mkdir -p "$TOOLS"
        if [ ! -x "$TOOLS/bin/micromamba" ]; then
            curl -fsSL https://micro.mamba.pm/api/micromamba/linux-64/latest |
                tar -xj -C "$TOOLS" bin/micromamba
        fi
        MAMBA_ROOT_PREFIX="$TOOLS/mamba" "$TOOLS/bin/micromamba" create -y -p "$TOOLKIT" \
            -c nvidia -c conda-forge "cuda-nvcc=12.8.*" "cuda-cudart-dev=12.8.*"
        touch "$TOOLKIT/.ready"
    else
        echo "[cuda-toolkit] exists, skipped"
    fi
}

drbokeh() {
    render_env
    cuda_toolkit
    local src="$TP/drbokeh"
    if [ ! -f "$src/.ready" ]; then
        echo "[drbokeh] clone at $DRBOKEH_SHA"
        mkdir -p "$TP"
        rm -rf "$src"
        git clone -q "$DRBOKEH_URL" "$src"
        git -C "$src" checkout -q "$DRBOKEH_SHA"
        # torch 2.11 removed the Tensor.type() call the dispatch macros used.
        sed -i 's/AT_DISPATCH_FLOATING_TYPES(\([a-z_]*\)\.type()/AT_DISPATCH_FLOATING_TYPES(\1.scalar_type()/' \
            "$src/app/cuda-src/scatter_cuda_kernel.cu"
        if grep -q 'AT_DISPATCH_FLOATING_TYPES([a-z_]*\.type()' "$src/app/cuda-src/scatter_cuda_kernel.cu"; then
            echo "error: the dispatch patch did not apply to $src" >&2
            exit 1
        fi
        touch "$src/.ready"
    else
        echo "[drbokeh] clone exists, skipped"
    fi
    if ! ls "$src"/app/cuda-src/scatter_cuda*.so > /dev/null 2>&1; then
        echo "[drbokeh] build scatter_cuda for this card"
        (
            cd "$src/app/cuda-src"
            export CUDA_HOME="$TOOLKIT" PATH="$TOOLKIT/bin:$PATH"
            # sm_120 on an RTX 5090: read the card's own capability.
            TORCH_CUDA_ARCH_LIST="$("$RENDER/bin/python" -c \
                'import torch; print("%d.%d" % torch.cuda.get_device_capability())')"
            export TORCH_CUDA_ARCH_LIST
            "$RENDER/bin/python" setup.py build_ext --inplace
        )
    else
        echo "[drbokeh] scatter_cuda built, skipped"
    fi
    "$RENDER/bin/python" - << PY
import sys

import torch  # noqa: F401  scatter_cuda needs its libraries loaded first

sys.path.insert(0, "$src/app/cuda-src")
import scatter_cuda  # noqa: F401

print("drbokeh ready")
PY
}

mpib() {
    render_env
    local src="$TP/mpib"
    if [ ! -f "$src/.ready" ]; then
        echo "[mpib] clone at $MPIB_SHA"
        mkdir -p "$TP"
        rm -rf "$src"
        git clone -q "$MPIB_URL" "$src"
        git -C "$src" checkout -q "$MPIB_SHA"
        # CuPy 13 removed the cupy.int alias that the launcher passes its sizes through.
        sed -i 's/cupy\.int(/int(/g' "$src/bokeh_generator.py"
        if grep -q 'cupy\.int(' "$src/bokeh_generator.py"; then
            echo "error: the cupy.int patch did not apply to $src" >&2
            exit 1
        fi
        touch "$src/.ready"
    else
        echo "[mpib] clone exists, skipped"
    fi
    uv pip install --python "$RENDER/bin/python" "cupy-cuda12x==14.2.0"
    "$RENDER/bin/python" - << PY
import sys

import cupy  # noqa: F401
import torch  # noqa: F401

sys.path.insert(0, "$src")
import bokeh_generator  # noqa: F401

print("mpib ready")
PY
}

case "${1:-}" in
    drbokeh) drbokeh ;;
    mpib) mpib ;;
    *)
        echo "usage: $0 drbokeh | mpib" >&2
        exit 1
        ;;
esac
