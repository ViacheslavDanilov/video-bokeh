#!/usr/bin/env bash
# Everything the lab-machine test runs, in order, into one log to send back.
#
# 1. The device check, with each depth estimator measured on this machine's GPU.
# 2. One library per depth estimator from the dev pools: all 30 foregrounds, no class
#    filter, and all 30 backgrounds, so every estimator sees the same assets.
# 3. The same sequences from each library: same seeds, so the scenes match and only the
#    disparity differs.
# 4. Their bokeh through any-to-bokeh, Stage C.
# 5. MP4s of each sequence's frames, disparity and bokeh, to look at.
#
# One estimator failing does not stop the others: it is named in the summary, and the
# run exits 1. A re-run picks up where the last stopped. A library or a bokeh stream
# that exists is not made again, and sequences are made again only when COUNT, FRAMES
# or SIZE changed, together with their bokeh. To redo an estimator from scratch, delete
# backend/data/lab/libraries/<estimator> and backend/data/lab/sequences/<estimator>.
#
# The output lands in backend/data/lab/, which git ignores, and
# `make api LIBRARY=backend/data/lab/libraries` shows the libraries in the page's picker.
#
# Prerequisites, once per machine, from the repository root:
#   make setup
#   scripts/setup_third_party.sh       # any-to-bokeh, its checkpoints, NVIDIA only
#   scripts/setup_depth_anything_3.sh  # the da3-* depth estimators
#
# Usage: scripts/lab_run.sh [--no-render] [estimator ...]
#   Estimators default to every registered one. --no-render stops before Stage C, for
#   checking the rest of this script on a machine without an NVIDIA card.
# Environment: COUNT sequences per estimator (4), FRAMES per sequence (80), SIZE (512).

set -euo pipefail

COUNT="${COUNT:-4}"
FRAMES="${FRAMES:-80}"
SIZE="${SIZE:-512}"
# Python's output reaches the log as it happens, not when a buffer fills.
export PYTHONUNBUFFERED=1

RENDER=1
ESTIMATORS=()
for arg in "$@"; do
    if [ "$arg" = "--no-render" ]; then
        RENDER=0
    else
        ESTIMATORS+=("$arg")
    fi
done

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
BACKEND="$REPO_ROOT/backend"
OUT="$BACKEND/data/lab"
A2B="$BACKEND/third_party/any-to-bokeh"
A2B_PYTHON="$A2B/.venv/bin/python"
DA3_PYTHON="$BACKEND/envs/depth-anything-3/.venv/bin/python"

py() { uv run --directory "$BACKEND" --extra library python "$@"; }

if [ "${#ESTIMATORS[@]}" -eq 0 ]; then
    read -r -a ESTIMATORS <<< "$(py -c \
        "from video_bokeh.library.depth import ESTIMATORS; print(' '.join(sorted(ESTIMATORS)))")"
else
    # A misspelt name would otherwise surface an hour in, as one failed library.
    py -c "import sys; from video_bokeh.library.depth import resolve_estimator; [resolve_estimator(s) for s in sys.argv[1:]]" \
        "${ESTIMATORS[@]}"
fi

# Stop before anything long, rather than an hour in.
if [ "$RENDER" = 1 ]; then
    for need in "$A2B_PYTHON" "$A2B/checkpoints/unet" "$A2B/checkpoints/vae"; do
        if [ ! -e "$need" ]; then
            echo "error: $need missing. Run scripts/setup_third_party.sh first." >&2
            exit 1
        fi
    done
fi
for estimator in "${ESTIMATORS[@]}"; do
    if [[ "$estimator" == da3-* ]] && [ ! -x "$DA3_PYTHON" ]; then
        echo "error: $DA3_PYTHON missing. Run scripts/setup_depth_anything_3.sh first." >&2
        exit 1
    fi
done

LOG_DIR="$BACKEND/data/measurements"
mkdir -p "$LOG_DIR" "$OUT/libraries" "$OUT/sequences"
LOG="$LOG_DIR/lab-$(date +%Y-%m-%d-%H%M%S).log"
echo "Logging to $LOG"
exec > >(tee "$LOG") 2>&1

# Each command as it would be typed again, quoting included.
run() {
    printf '\n$'
    printf ' %q' "$@"
    printf '\n'
    "$@"
}

SUMMARY=()
FAILED=()
# Runs a step, records its time and whether it failed, and never stops the script.
timed() {
    local label="$1"
    shift
    local start=$SECONDS status=0
    run "$@" || status=$?
    local outcome="ok"
    [ "$status" -ne 0 ] && outcome="FAILED, exit $status"
    SUMMARY+=("$(printf '%-36s %6d s  %s' "$label" $((SECONDS - start)) "$outcome")")
    return "$status"
}

finish() {
    local status=$?
    printf '\n===== summary =====\n'
    if [ "${#SUMMARY[@]}" -gt 0 ]; then
        printf '%s\n' "${SUMMARY[@]}"
    fi
    if [ "${#FAILED[@]}" -gt 0 ]; then
        printf '\nFailed:\n'
        printf '  %s\n' "${FAILED[@]}"
    fi
    printf '\nLibraries: %s\nSequences: %s\n' "$OUT/libraries" "$OUT/sequences"
    printf 'In the page: make api LIBRARY=%s, then make web\n' "$OUT/libraries"
    printf '\nSend back: %s\n' "$LOG"
    exit "$status"
}
trap finish EXIT

printf 'lab-machine run\n'
printf 'date:       %s\n' "$(date -Iseconds)"
printf 'host:       %s\n' "$(hostname)"
printf 'commit:     %s\n' "$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
printf 'estimators: %s\n' "${ESTIMATORS[*]}"
printf 'sequences:  %s per estimator, %s frames at %s px\n' "$COUNT" "$FRAMES" "$SIZE"

printf '\n===== environment =====\n'
if command -v nvidia-smi > /dev/null; then
    run nvidia-smi
else
    echo "no nvidia-smi on this machine"
fi
TORCH='import torch; print("torch", torch.__version__, "| cuda", torch.version.cuda, "| available", torch.cuda.is_available())'
run uv run --directory "$BACKEND" --extra library python -c "$TORCH"
[ -x "$DA3_PYTHON" ] && run "$DA3_PYTHON" -c "$TORCH"
[ -x "$A2B_PYTHON" ] && run "$A2B_PYTHON" -c "$TORCH"

printf '\n===== 1. device check, measured =====\n'
model_flags=()
for estimator in "${ESTIMATORS[@]}"; do
    model_flags+=(--model "$estimator")
done
# Not ready is a finding to send back, not a reason to stop: the summary says so.
timed "device check" py -m video_bokeh.library.check --measure "${model_flags[@]}" ||
    FAILED+=("device check")

READY=()
printf '\n===== 2. one library per depth estimator =====\n'
for estimator in "${ESTIMATORS[@]}"; do
    # One make call each, so a build that fails leaves the others to run. No class filter:
    # all 30 foregrounds, as the comparison is meant to see them.
    if timed "library, $estimator" make -C "$REPO_ROOT" libraries \
        LIBRARY="$OUT/libraries" ESTIMATORS="$estimator" \
        BUILD_FLAGS="--subjects , --styles , --subject-thr 0"; then
        READY+=("$estimator")
    else
        FAILED+=("library $estimator")
    fi
done

printf '\n===== 3. the same sequences from each library =====\n'
SETTINGS="count=$COUNT frames=$FRAMES size=$SIZE"
GENERATED=()
# The ${a[@]+...} form keeps an empty array from tripping set -u on bash 3.2, which
# macOS still ships.
for estimator in ${READY[@]+"${READY[@]}"}; do
    dest="$OUT/sequences/$estimator"
    # Stage B writes manifest.csv last, so its presence means the set finished.
    if [ -f "$dest/manifest.csv" ] && [ "$(cat "$dest/.lab-settings" 2> /dev/null)" = "$SETTINGS" ]; then
        echo "$estimator: sequences exist for $SETTINGS, skipped"
        GENERATED+=("$estimator")
        continue
    fi
    # Different settings or an unfinished set: start over, bokeh included.
    rm -rf "$dest"
    if timed "sequences, $estimator" uv run --directory "$BACKEND" \
        python -m video_bokeh.scenes.generate --library-root "$OUT/libraries/$estimator" \
        --output "$dest" --count "$COUNT" --frames "$FRAMES" --size "$SIZE" --seed 0; then
        echo "$SETTINGS" > "$dest/.lab-settings"
        GENERATED+=("$estimator")
    else
        FAILED+=("sequences $estimator")
    fi
done

if [ "$RENDER" = 1 ]; then
    printf '\n===== 4. bokeh, Stage C =====\n'
    for estimator in ${GENERATED[@]+"${GENERATED[@]}"}; do
        dest="$OUT/sequences/$estimator"
        # A sequence's bokeh/ appears whole or not at all, so a missing one is all to redo.
        missing=$(find "$dest/sequences" -mindepth 1 -maxdepth 1 -type d \
            ! -exec test -d '{}/bokeh' ';' -print | wc -l)
        if [ "$missing" -eq 0 ]; then
            echo "$estimator: bokeh exists, skipped"
            continue
        fi
        timed "bokeh, $estimator" uv run --directory "$BACKEND" --extra render \
            python -m video_bokeh.render.run --data-root "$dest" ||
            FAILED+=("bokeh $estimator")
    done
else
    printf '\n===== 4. bokeh, Stage C: skipped (--no-render) =====\n'
fi

printf '\n===== 5. MP4s to look at =====\n'
for estimator in ${GENERATED[@]+"${GENERATED[@]}"}; do
    dest="$OUT/sequences/$estimator"
    streams="all_in_focus,disparity"
    if [ -n "$(find "$dest/sequences" -mindepth 2 -maxdepth 2 -type d -name bokeh -print -quit)" ]; then
        streams="$streams,bokeh"
    fi
    run uv run --directory "$BACKEND" --extra preview \
        python -m video_bokeh.preview.pack --data-root "$dest" --streams "$streams" ||
        FAILED+=("mp4 $estimator")
done

[ "${#FAILED[@]}" -eq 0 ]
