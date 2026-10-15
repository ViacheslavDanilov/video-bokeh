#!/usr/bin/env bash
# Everything the lab-machine test runs, in order, into one log to send back.
#
# 1. The device check, with each depth estimator measured on this machine's GPU.
# 2. One library per depth estimator from the dev pools: all 30 foregrounds, no class
#    filter, and all 30 backgrounds, so every estimator sees the same assets.
# 3. The same sequences from each library, with their bokeh rendered in the same run:
#    same seeds, so the scenes match and only the disparity differs.
# 4. MP4s of each sequence's frames, disparity and bokeh, to look at.
#
# One estimator failing does not stop the others: it is named in the summary, and the
# run exits 1. A re-run picks up where the last stopped. A library that exists is not
# made again, and sequences are made again only when COUNT, FRAMES or SIZE changed. To
# redo an estimator from scratch, delete backend/data/lab/libraries/<estimator> and
# backend/data/lab/sequences/<estimator>.
#
# The output lands in backend/data/lab/, which git ignores, and
# `make api LIBRARY=backend/data/lab/libraries` shows the libraries in the page's picker.
#
# Depth Anything 3 runs in its Docker image where Linux has docker with the NVIDIA runtime,
# and in its venv elsewhere; VIDEO_BOKEH_RUNNER=docker or local chooses outright. The other
# depth models run in this process.
#
# Prerequisites, once per machine, from the repository root:
#   make setup
#   make images                        # Depth Anything 3's image, for the docker runner
#   scripts/setup_depth_anything_3.sh  # the da3-* venv, for the local runner only
#
# Usage: scripts/lab_run.sh [estimator ...]
#   Estimators default to every registered one.
# Environment: COUNT sequences per estimator (4), FRAMES per sequence (80), SIZE (512),
# VIDEO_BOKEH_RUNNER (docker on Linux with docker's NVIDIA runtime, local otherwise).

set -euo pipefail

COUNT="${COUNT:-4}"
FRAMES="${FRAMES:-80}"
SIZE="${SIZE:-512}"
# Python's output reaches the log as it happens, not when a buffer fills.
export PYTHONUNBUFFERED=1

ESTIMATORS=("$@")

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
BACKEND="$REPO_ROOT/backend"
OUT="$BACKEND/data/lab"
DA3_PYTHON="$BACKEND/envs/depth-anything-3/.venv/bin/python"

py() { uv run --directory "$BACKEND" --extra library python "$@"; }

if [ -z "${VIDEO_BOKEH_RUNNER:-}" ]; then
    # A daemon this user can reach, with a GPU to give a container: not Docker on a Mac,
    # not a Linux box without an NVIDIA card, not a shell outside the docker group.
    if [ "$(uname)" = Linux ] &&
        docker info --format '{{json .Runtimes}}' 2> /dev/null | grep -q '"nvidia"'; then
        VIDEO_BOKEH_RUNNER=docker
    else
        VIDEO_BOKEH_RUNNER=local
    fi
fi
case "$VIDEO_BOKEH_RUNNER" in
    local | docker) ;;
    *)
        echo "error: VIDEO_BOKEH_RUNNER must be local or docker, not $VIDEO_BOKEH_RUNNER" >&2
        exit 1
        ;;
esac
export VIDEO_BOKEH_RUNNER

if [ "${#ESTIMATORS[@]}" -eq 0 ]; then
    read -r -a ESTIMATORS <<< "$(py -c \
        "from video_bokeh.library.depth import ESTIMATORS; print(' '.join(sorted(ESTIMATORS)))")"
else
    # A misspelled name would otherwise surface an hour in, as one failed library.
    py -c "import sys; from video_bokeh.library.depth import resolve_estimator; [resolve_estimator(s) for s in sys.argv[1:]]" \
        "${ESTIMATORS[@]}"
fi

# Stop before anything long, rather than an hour in.
if [ "$VIDEO_BOKEH_RUNNER" = docker ]; then
    # The images the run needs, each once, as the classes name them; an estimator of your
    # own with none runs in this process. A failure here must stop the run rather than
    # leave the list empty and the check skipped.
    listed="$(py -c "
import sys
from video_bokeh.library.depth import resolve_estimator
classes = [resolve_estimator(s) for s in sys.argv[1:]]
names = [getattr(cls, 'docker_image', '') for cls in classes]
print(' '.join(dict.fromkeys(n for n in names if n)))
" "${ESTIMATORS[@]}")"
    read -r -a images <<< "$listed"
    for image in ${images[@]+"${images[@]}"}; do
        if ! problem="$(docker image inspect "$image" 2>&1 > /dev/null)"; then
            # Only a missing image is the image's fault; anything else says so itself.
            if grep -qi "no such image" <<< "$problem"; then
                echo "error: no Docker image $image. Run make images first." >&2
            else
                echo "error: docker cannot inspect $image: $problem" >&2
            fi
            exit 1
        fi
    done
else
    for estimator in "${ESTIMATORS[@]}"; do
        if [[ "$estimator" == da3-* ]] && [ ! -x "$DA3_PYTHON" ]; then
            echo "error: $DA3_PYTHON missing. Run scripts/setup_depth_anything_3.sh first." >&2
            exit 1
        fi
    done
fi

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
printf 'runner:     %s\n' "$VIDEO_BOKEH_RUNNER"

printf '\n===== environment =====\n'
if command -v nvidia-smi > /dev/null; then
    run nvidia-smi
else
    echo "no nvidia-smi on this machine"
fi
TORCH='import torch; print("torch", torch.__version__, "| cuda", torch.version.cuda, "| available", torch.cuda.is_available())'
# A venv whose torch will not import is a finding for the log, not a reason to stop here:
# the step that needs it fails on its own and says so.
run uv run --directory "$BACKEND" --extra library python -c "$TORCH" || true
if [ "$VIDEO_BOKEH_RUNNER" = docker ]; then
    for image in ${images[@]+"${images[@]}"}; do
        run docker run --rm --gpus all "$image" python -c "$TORCH" || true
    done
else
    if [ -x "$DA3_PYTHON" ]; then run "$DA3_PYTHON" -c "$TORCH" || true; fi
fi

printf '\n===== 1. device check, measured =====\n'
model_flags=()
for estimator in "${ESTIMATORS[@]}"; do
    model_flags+=(--model "$estimator")
done
# Not ready is a finding to send back, not a reason to stop: the summary says so.
timed "device check" uv run --directory "$BACKEND" --extra library \
    python -m video_bokeh.library.check --measure "${model_flags[@]}" ||
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

printf '\n===== 3. the same sequences from each library, with their bokeh =====\n'
SETTINGS="count=$COUNT frames=$FRAMES size=$SIZE"
GENERATED=()
# The ${a[@]+...} form keeps an empty array from tripping set -u on bash 3.2, which
# macOS still ships.
for estimator in ${READY[@]+"${READY[@]}"}; do
    dest="$OUT/sequences/$estimator"
    # Stage B writes manifest.csv last, after objects.csv and run.json, so its
    # presence means the set and its records finished.
    if [ -f "$dest/manifest.csv" ] && [ "$(cat "$dest/.lab-settings" 2> /dev/null)" = "$SETTINGS" ]; then
        echo "$estimator: sequences exist for $SETTINGS, skipped"
        GENERATED+=("$estimator")
        continue
    fi
    # Different settings or an unfinished set: start over.
    rm -rf "$dest"
    generated=0
    timed "sequences, $estimator" uv run --directory "$BACKEND" --extra render \
        python -m video_bokeh.scenes.generate --library-root "$OUT/libraries/$estimator" \
        --output "$dest" --count "$COUNT" --frames "$FRAMES" --size "$SIZE" --seed 0 \
        --bokeh ||
        generated=$?
    if [ "$generated" -ne 0 ]; then
        FAILED+=("sequences $estimator")
    elif [ ! -d "$dest/sequences" ]; then
        # Stage B exits 0 having written nothing when every seed runs out of retries.
        FAILED+=("sequences $estimator: Stage B wrote none")
    else
        echo "$SETTINGS" > "$dest/.lab-settings"
        GENERATED+=("$estimator")
    fi
done

printf '\n===== 4. MP4s to look at =====\n'
for estimator in ${GENERATED[@]+"${GENERATED[@]}"}; do
    dest="$OUT/sequences/$estimator"
    run uv run --directory "$BACKEND" --extra preview \
        python -m video_bokeh.preview.pack --data-root "$dest" \
        --streams all_in_focus,disparity,bokeh ||
        FAILED+=("mp4 $estimator")
done

[ "${#FAILED[@]}" -eq 0 ]
