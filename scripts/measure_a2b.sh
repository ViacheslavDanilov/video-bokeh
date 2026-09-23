#!/usr/bin/env bash
# Measure any-to-bokeh inference cost end to end, on a sequence this repo generated.
# CUDA-only: test/inference_demo.py hardcodes cuda:0, so this needs the lab machine.
#
# It answers one question the design spec has left open since 2026-09-18 — what a
# single 80-frame sequence costs to render — and it answers it with a number, not a
# recollection. Everything it runs is echoed into a log, so the log alone is enough
# to report back with.
#
# Four steps, each skippable, each idempotent:
#   1. Environment: GPU, driver, torch build. Recorded because seconds per frame
#      mean nothing without the card they were measured on.
#   2. Stage A + Stage B via scripts/build_dataset.py, into their own directories
#      so an existing data/demo is never touched.
#   3. The bridge: our sequence layout -> the layout a2b reads.
#   4. Inference, wall-clocked.
#
# Usage: scripts/measure_a2b.sh [--frames N] [--size N] [--start-from N] [--keep]
#        --frames      frames per sequence (default 80, the number the estimate refers to)
#        --size        square frame side before a2b resizes it (default 512)
#        --start-from  step 1-4 to start from; earlier steps are skipped
#        --keep        leave the bridge's output inside the submodule
#
# Run it from anywhere in the checkout. Prerequisite: scripts/setup_third_party.sh
# has been run once on this machine.

set -euo pipefail

FRAMES=80
SIZE=512
START_FROM=1
KEEP=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --frames)     FRAMES="${2:?error: --frames requires a number}"; shift 2 ;;
        --size)       SIZE="${2:?error: --size requires a number}"; shift 2 ;;
        --start-from) START_FROM="${2:?error: --start-from requires a step number (1-4)}"; shift 2 ;;
        --keep)       KEEP=1; shift ;;
        *)
            echo "error: unknown argument '$1'" >&2
            echo "usage: $0 [--frames N] [--size N] [--start-from N] [--keep]" >&2
            exit 1
            ;;
    esac
done

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
BACKEND="$REPO_ROOT/backend"
A2B_DIR="$BACKEND/third_party/any-to-bokeh"
VENV="$A2B_DIR/.venv"
DATASET_NAME="measure"

# Own directories, so an existing data/demo survives. Both are gitignored by
# backend/data/*/ and backend/data/library*/.
LIBRARY="data/library_a2b_measure"
OUTPUT="data/a2b_measure"

LOG_DIR="$BACKEND/data/measurements"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/a2b-$(date +%Y-%m-%d-%H%M%S).log"

# Everything below is teed into the log, so the log is a complete transcript.
exec > >(tee "$LOG") 2>&1

# Echo a command, then run it. The log doubles as the copy-paste recipe.
run() {
    printf '\n$ %s\n' "$*"
    "$@"
}

section() {
    printf '\n========== %s ==========\n' "$1"
}

# The bridge writes into a read-only submodule checkout. Clean it on the way out
# whatever happens -- an inference that dies half way through used to leave the
# converted inputs behind, and the next `git status` in there then lies.
cleanup() {
    if [ "$KEEP" -eq 1 ]; then
        return
    fi
    if [ -e "$A2B_DIR/demo_dataset/$DATASET_NAME" ] || [ -e "$A2B_DIR/csv_file/$DATASET_NAME.csv" ]; then
        section "cleanup"
        rm -rf "$A2B_DIR/demo_dataset/$DATASET_NAME" "$A2B_DIR/csv_file/$DATASET_NAME.csv"
        echo "Removed the converted inputs from the submodule."
        echo "Rendered videos under $A2B_DIR/output/ are left in place."
        echo "Re-run with --keep to also keep the converted inputs."
    fi
}
trap cleanup EXIT

# inference_demo.py runs out of the submodule's own venv, not ours. Checked here
# rather than only in step 1, because --start-from skips step 1 and the failure
# would otherwise be a bare "No such file or directory" at the last step.
require_a2b_venv() {
    if [ ! -x "$VENV/bin/python" ]; then
        echo "error: $VENV/bin/python missing." >&2
        echo "       Run scripts/setup_third_party.sh first. CUDA-only -- this needs the lab machine." >&2
        exit 1
    fi
}

printf 'any-to-bokeh inference measurement\n'
printf 'date:    %s\n' "$(date -Iseconds)"
printf 'host:    %s\n' "$(hostname)"
printf 'commit:  %s\n' "$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
printf 'frames:  %s\n' "$FRAMES"
printf 'size:    %s\n' "$SIZE"
printf 'log:     %s\n' "$LOG"

# 1. Environment ---------------------------------------------------------------
if [ "$START_FROM" -le 1 ]; then
    section "1/4 environment"
    if command -v nvidia-smi >/dev/null 2>&1; then
        run nvidia-smi
    else
        echo "warning: nvidia-smi not found. inference_demo.py needs cuda:0 and will fail."
    fi
    require_a2b_venv
    run "$VENV/bin/python" -c \
        "import torch; print('torch', torch.__version__, '| cuda', torch.version.cuda, '| available', torch.cuda.is_available())"
else
    section "1/4 environment -- skipped"
fi

# 2. Generate a sequence -------------------------------------------------------
if [ "$START_FROM" -le 2 ]; then
    section "2/4 generate one sequence (Stage A + Stage B)"
    run uv run --directory "$BACKEND" python "$REPO_ROOT/scripts/build_dataset.py" \
        --library "$LIBRARY" \
        --output "$OUTPUT" \
        --count 1 \
        --frames "$FRAMES" \
        --size "$SIZE" \
        --n-objects-min 4 \
        --n-objects-max 5
else
    section "2/4 generate -- skipped"
fi

# 3. Bridge --------------------------------------------------------------------
if [ "$START_FROM" -le 3 ]; then
    section "3/4 convert to the any-to-bokeh layout"
    run uv run --directory "$BACKEND" python -m video_bokeh.bridge.any_to_bokeh \
        --data-root "$OUTPUT" \
        --dataset-name "$DATASET_NAME"
else
    section "3/4 bridge -- skipped"
fi

CSV="csv_file/$DATASET_NAME.csv"
if [ ! -f "$A2B_DIR/$CSV" ]; then
    echo "error: $A2B_DIR/$CSV missing -- step 3 did not run or failed." >&2
    exit 1
fi

# 4. Inference -----------------------------------------------------------------
section "4/4 inference"
require_a2b_venv
echo "Fixed by test/inference_demo.py, not by us: output 576x1024, group_frames=8,"
echo "overlap_frames=4, num_inference_steps=1. Our ${SIZE}x${SIZE} frames are resized"
echo "to that shape, so the rendered aspect ratio is not the one we generated."

printf '\n$ cd %s && .venv/bin/python test/inference_demo.py --val_csv_path %s\n' "$A2B_DIR" "$CSV"

START_NS=$(date +%s)
(cd "$A2B_DIR" && "$VENV/bin/python" test/inference_demo.py --val_csv_path "$CSV")
END_NS=$(date +%s)
ELAPSED=$((END_NS - START_NS))

# Report ------------------------------------------------------------------------
section "result"
printf 'frames:            %s\n' "$FRAMES"
printf 'wall clock:        %s s\n' "$ELAPSED"
if [ "$FRAMES" -gt 0 ]; then
    printf 'per frame:         %s s\n' "$(awk -v e="$ELAPSED" -v f="$FRAMES" 'BEGIN{printf "%.3f", e/f}')"
fi
printf 'output:            %s/output/\n' "$A2B_DIR"
if [ -d "$A2B_DIR/output" ]; then
    run ls -la "$A2B_DIR/output"
fi
printf '\nlog written to: %s\n' "$LOG"
printf 'Send that file back - it carries the commands, the GPU and the timing.\n'
