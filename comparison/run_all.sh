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
# Each method needs its own setup, once: comparison/setup.sh drbokeh | mpib | bokehme | a2b;
# a method not set up stops the run before it starts. A method that fails stops it, the last
# "== name" line says which, and the ones before it keep their files. Use a data root that
# holds only the sequences you want in the table: the summary refuses files made over
# different sequences.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/envs/render/bin/python"
DATA="${1:?usage: $0 <data-root> [sequence ids]}"
SEQS="${2:-}"
seqs_arg=()
[ -n "$SEQS" ] && seqs_arg=(--seqs "$SEQS")

# Every method set up, before anything long starts rather than minutes in.
missing=()
[ -x "$PY" ] || missing+=("render environment: setup.sh drbokeh")
for method in drbokeh mpib bokehme; do
    [ -f "$HERE/third_party/$method/.ready" ] || missing+=("$method: setup.sh $method")
done
[ -f "$HERE/third_party/any-to-bokeh/.ready" ] && [ -f "$HERE/envs/any-to-bokeh/.ready" ] ||
    missing+=("any-to-bokeh: setup.sh a2b")
if [ "${#missing[@]}" -gt 0 ]; then
    echo "error: not set up, run comparison/setup.sh for each:" >&2
    printf '  %s\n' "${missing[@]}" >&2
    exit 1
fi

# The methods' own source has invalid escape sequences in regular expressions, which Python
# warns of on every start; those warnings are all this hides.
for adapter in drbokeh mpib_rt bokehme any_to_bokeh; do
    echo "== $adapter"
    "$PY" -W ignore::SyntaxWarning "$HERE/run_$adapter.py" --data-root "$DATA" \
        ${seqs_arg[@]+"${seqs_arg[@]}"}
done
for method in drbokeh mpib_rt bokehme bokehme_classical any_to_bokeh; do
    echo "== score $method"
    "$PY" "$HERE/score.py" --data-root "$DATA" --method "$method" ${seqs_arg[@]+"${seqs_arg[@]}"}
done
echo "== summary"
"$PY" "$HERE/summary.py" --data-root "$DATA"
