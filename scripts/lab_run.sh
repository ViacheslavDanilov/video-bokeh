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
# A re-run picks up where the last stopped: a library, a set of sequences or a bokeh
# stream that exists is not made again. The output lands in backend/data/lab/, which git
# ignores, and `make api LIBRARY=backend/data/lab/libraries` shows the libraries in the
# page's depth estimator picker.
#
# Prerequisites, once per machine, from the repository root:
#   make setup
#   scripts/setup_third_party.sh       # any-to-bokeh, its checkpoints, NVIDIA only
#   scripts/setup_depth_anything_3.sh  # the da3-* depth estimators
#
# Usage: scripts/lab_run.sh [--no-render] [estimator ...]
#   estimators default to every registered one; --no-render stops before Stage C, for
#   checking the rest of this script on a machine without an NVIDIA card.
# Environment: COUNT sequences per estimator (4), FRAMES per sequence (80), SIZE (512).

set -euo pipefail

COUNT="${COUNT:-4}"
FRAMES="${FRAMES:-80}"
SIZE="${SIZE:-512}"

RENDER=1
if [ "${1:-}" = "--no-render" ]; then
    RENDER=0
    shift
fi

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
BACKEND="$REPO_ROOT/backend"
OUT="$BACKEND/data/lab"
A2B_PYTHON="$BACKEND/third_party/any-to-bokeh/.venv/bin/python"
DA3_PYTHON="$BACKEND/envs/depth-anything-3/.venv/bin/python"

if [ "$#" -gt 0 ]; then
    ESTIMATORS="$*"
else
    ESTIMATORS="$(uv run --directory "$BACKEND" --extra library python -c \
        "from video_bokeh.library.depth import ESTIMATORS; print(' '.join(sorted(ESTIMATORS)))")"
fi

# Stop before anything long, rather than an hour in.
if [ "$RENDER" = 1 ] && [ ! -x "$A2B_PYTHON" ]; then
    echo "error: $A2B_PYTHON missing. Run scripts/setup_third_party.sh first." >&2
    exit 1
fi
case " $ESTIMATORS " in
*" da3-"*)
    if [ ! -x "$DA3_PYTHON" ]; then
        echo "error: $DA3_PYTHON missing. Run scripts/setup_depth_anything_3.sh first." >&2
        exit 1
    fi
    ;;
esac

LOG_DIR="$BACKEND/data/measurements"
mkdir -p "$LOG_DIR" "$OUT/libraries" "$OUT/sequences"
LOG="$LOG_DIR/lab-$(date +%Y-%m-%d-%H%M%S).log"
exec > >(tee "$LOG") 2>&1

run() { printf '\n$ %s\n' "$*"; "$@"; }
SUMMARY=()
timed() {
    local label="$1"
    shift
    local start=$SECONDS
    run "$@"
    SUMMARY+=("$(printf '%-44s %6d s' "$label" $((SECONDS - start)))")
}

printf 'lab-machine run\n'
printf 'date:       %s\n' "$(date -Iseconds)"
printf 'host:       %s\n' "$(hostname)"
printf 'commit:     %s\n' "$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
printf 'estimators: %s\n' "$ESTIMATORS"
printf 'sequences:  %s per estimator, %s frames at %s px\n' "$COUNT" "$FRAMES" "$SIZE"

printf '\n===== environment =====\n'
if command -v nvidia-smi > /dev/null; then
    run nvidia-smi
else
    echo "no nvidia-smi on this machine"
fi
run uv run --directory "$BACKEND" --extra library python -c \
    "import torch; print('torch', torch.__version__, '| cuda', torch.version.cuda, '| available', torch.cuda.is_available())"

printf '\n===== 1. device check, measured =====\n'
model_flags=()
for estimator in $ESTIMATORS; do
    model_flags+=(--model "$estimator")
done
# Not ready is a finding to send back, not a reason to stop.
timed "device check" uv run --directory "$BACKEND" --extra library \
    python -m video_bokeh.library.check --measure "${model_flags[@]}" || true

printf '\n===== 2. one library per depth estimator =====\n'
# No class filter: all 30 foregrounds, as the comparison is meant to see them.
timed "libraries" make -C "$REPO_ROOT" libraries LIBRARY="$OUT/libraries" \
    ESTIMATORS="$ESTIMATORS" BUILD_FLAGS="--subjects , --styles , --subject-thr 0"

printf '\n===== 3. the same sequences from each library =====\n'
for estimator in $ESTIMATORS; do
    dest="$OUT/sequences/$estimator"
    if [ -d "$dest/sequences" ] &&
        [ "$(find "$dest/sequences" -mindepth 1 -maxdepth 1 -type d | wc -l)" -ge "$COUNT" ]; then
        echo "$estimator: sequences exist, skipped"
        continue
    fi
    timed "sequences, $estimator" uv run --directory "$BACKEND" \
        python -m video_bokeh.scenes.generate --library-root "$OUT/libraries/$estimator" \
        --output "$dest" --count "$COUNT" --frames "$FRAMES" --size "$SIZE" --seed 0
done

if [ "$RENDER" = 1 ]; then
    printf '\n===== 4. bokeh, Stage C =====\n'
    for estimator in $ESTIMATORS; do
        dest="$OUT/sequences/$estimator"
        missing=$(find "$dest/sequences" -mindepth 1 -maxdepth 1 -type d ! -exec test -d '{}/bokeh' ';' -print | wc -l)
        if [ "$missing" -eq 0 ]; then
            echo "$estimator: bokeh exists, skipped"
            continue
        fi
        timed "bokeh, $estimator" uv run --directory "$BACKEND" --extra render \
            python -m video_bokeh.render.run --data-root "$dest"
    done
else
    printf '\n===== 4. bokeh, Stage C: skipped (--no-render) =====\n'
fi

printf '\n===== 5. MP4s to look at =====\n'
streams="all_in_focus,disparity"
[ "$RENDER" = 1 ] && streams="$streams,bokeh"
for estimator in $ESTIMATORS; do
    run uv run --directory "$BACKEND" --extra preview \
        python -m video_bokeh.preview.pack --data-root "$OUT/sequences/$estimator" \
        --streams "$streams"
done

printf '\n===== summary =====\n'
printf '%s\n' "${SUMMARY[@]}"
printf '\nLibraries: %s\nSequences: %s\n' "$OUT/libraries" "$OUT/sequences"
printf 'In the page: make api LIBRARY=%s, then make web\n' "$OUT/libraries"
printf '\nSend back: %s\n' "$LOG"
