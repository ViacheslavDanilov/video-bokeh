#!/usr/bin/env bash
# Measure what any-to-bokeh inference costs for one 80-frame sequence.
#
# The design spec has carried this as an open question since 2026-09-18, and the
# figure in circulation -- "about a minute" -- is a recollection. It cannot be
# answered on a laptop: test/inference_demo.py is pinned to cuda:0 in six places.
#
# Run it on the lab machine, then send back the log it writes. That file carries the
# commands, the GPU and the timing together, which is the whole point of having a
# script rather than a list of commands to copy.
#
# Prerequisite: scripts/setup_third_party.sh has been run once on this machine.
# Usage: scripts/measure_a2b.sh

set -euo pipefail

FRAMES=80
SIZE=512
DATASET=measure

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
BACKEND="$REPO_ROOT/backend"
A2B="$BACKEND/third_party/any-to-bokeh"
VENV="$A2B/.venv"

if [ ! -x "$VENV/bin/python" ]; then
    echo "error: $VENV/bin/python missing. Run scripts/setup_third_party.sh first." >&2
    exit 1
fi

LOG_DIR="$BACKEND/data/measurements"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/a2b-$(date +%Y-%m-%d-%H%M%S).log"
exec > >(tee "$LOG") 2>&1

# The bridge writes into a read-only submodule checkout. Clean it on the way out
# whatever happens, or a failed inference leaves that tree dirty for good.
trap 'rm -rf "$A2B/demo_dataset/$DATASET" "$A2B/csv_file/$DATASET.csv"' EXIT

run() { printf '\n$ %s\n' "$*"; "$@"; }

printf 'any-to-bokeh inference measurement\n'
printf 'date:   %s\n' "$(date -Iseconds)"
printf 'host:   %s\n' "$(hostname)"
printf 'commit: %s\n' "$(git -C "$REPO_ROOT" rev-parse --short HEAD)"

# Seconds per frame mean nothing without the card they were measured on.
printf '\n===== environment =====\n'
run nvidia-smi
run "$VENV/bin/python" -c \
    "import torch; print('torch', torch.__version__, '| cuda', torch.version.cuda, '| available', torch.cuda.is_available())"

# Its own directories, so an existing data/demo survives. Both are gitignored.
printf '\n===== generate one sequence =====\n'
run uv run --directory "$BACKEND" python "$REPO_ROOT/scripts/build_dataset.py" \
    --library data/library_a2b_measure --output data/a2b_measure \
    --count 1 --frames "$FRAMES" --size "$SIZE" --n-objects-min 4 --n-objects-max 5

printf '\n===== convert to the any-to-bokeh layout =====\n'
run uv run --directory "$BACKEND" python -m video_bokeh.bridge.any_to_bokeh \
    --data-root data/a2b_measure --dataset-name "$DATASET"

printf '\n===== inference =====\n'
echo "Fixed by inference_demo.py, not by us: output 576x1024, group_frames=8,"
echo "overlap_frames=4, num_inference_steps=1. Our ${SIZE}x${SIZE} frames are resized to"
echo "that shape, so the rendered aspect ratio is not the one we generated."
printf '\n$ cd %s && .venv/bin/python test/inference_demo.py --val_csv_path csv_file/%s.csv\n' "$A2B" "$DATASET"

START=$(date +%s)
(cd "$A2B" && "$VENV/bin/python" test/inference_demo.py --val_csv_path "csv_file/$DATASET.csv")
ELAPSED=$(($(date +%s) - START))

printf '\n===== result =====\n'
printf 'frames:     %s\n' "$FRAMES"
printf 'wall clock: %s s\n' "$ELAPSED"
printf 'per frame:  %s s\n' "$(awk -v e="$ELAPSED" -v f="$FRAMES" 'BEGIN{printf "%.3f", e/f}')"
run ls -la "$A2B/output"
printf '\nSend back: %s\n' "$LOG"
