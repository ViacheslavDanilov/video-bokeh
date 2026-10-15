#!/usr/bin/env bash
# Run every comparison method over written sequences, score each against our bokeh, and print
# one table. The sequences must hold their layers and bokeh, so that the focus and the
# strength are ours: write them with
#
#   uv run python -m video_bokeh.scenes.generate --library-root <library> --output <dir> \
#     --count <n> --frames 24 --size 1024 --seed <s> --layers --bokeh
#
# Usage: comparison/run_all.sh <data-root> [sequence ids, comma-separated]
#
# Each method needs its own setup, once: comparison/setup.sh drbokeh | mpib | bokehme | a2b.
# A method that fails stops the run, naming itself, and the ones before it keep their files.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/envs/render/bin/python"
DATA="${1:?usage: $0 <data-root> [sequence ids]}"
SEQS="${2:-}"
seqs_arg=()
[ -n "$SEQS" ] && seqs_arg=(--seqs "$SEQS")

for adapter in drbokeh mpib_rt bokehme any_to_bokeh; do
    echo "== $adapter"
    "$PY" -W ignore "$HERE/run_$adapter.py" --data-root "$DATA" ${seqs_arg[@]+"${seqs_arg[@]}"}
done
for method in drbokeh mpib_rt bokehme bokehme_classical any_to_bokeh; do
    echo "== score $method"
    "$PY" "$HERE/score.py" --data-root "$DATA" --method "$method" ${seqs_arg[@]+"${seqs_arg[@]}"}
done
echo "== summary"
"$PY" "$HERE/summary.py" --data-root "$DATA"
