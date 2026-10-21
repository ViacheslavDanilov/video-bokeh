#!/usr/bin/env bash
# Run every comparison method over written sequences, score each against our bokeh and against
# MPIB's ray tracer composited in gamma values, and print a table of each. The sequences must
# hold their layers and bokeh, so that the focus and the strength are ours: write them with
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
# different sequences. The scores against MPIB go into <data-root>/vs_mpib, a data root of
# links to the same sequences, so that each score file keeps its name.

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

# Our renderer on one frame runs on the GPU unless told otherwise.
export VIDEO_BOKEH_LAYERED_DEVICE="${VIDEO_BOKEH_LAYERED_DEVICE:-cuda:0}"

# The methods' own source has invalid escape sequences in regular expressions, which Python
# warns of on every start; those warnings are all this hides.
# Dr.Bokeh and MPIB run twice: as published, compositing in linear light, and compositing in
# gamma values, as Stage B and our renderer do.
for run in drbokeh mpib_rt drbokeh:gamma mpib_rt:gamma bokehme ours_one_frame any_to_bokeh; do
    adapter="${run%%:*}"
    composite=()
    [ "$adapter" != "$run" ] && composite=(--composite "${run#*:}")
    echo "== $run"
    "$PY" -W ignore::SyntaxWarning "$HERE/run_$adapter.py" --data-root "$DATA" \
        ${composite[@]+"${composite[@]}"} ${seqs_arg[@]+"${seqs_arg[@]}"}
done
for method in drbokeh drbokeh_cg mpib_rt mpib_rt_cg bokehme bokehme_classical ours_one_frame any_to_bokeh; do
    echo "== score $method"
    "$PY" "$HERE/score.py" --data-root "$DATA" --method "$method" ${seqs_arg[@]+"${seqs_arg[@]}"}
done
echo "== summary, against ours"
"$PY" "$HERE/summary.py" --data-root "$DATA"

# MPIB composited in gamma values is the reference our frames agree with at every in-focus edge;
# against it, ours is the mpib_rt_cg row above, as both scores are symmetric.
VS="$DATA/vs_mpib"
rm -rf "$VS"
mkdir -p "$VS/sequences"
for seq in "$DATA"/sequences/*/; do
    ln -s "$(cd "$seq" && pwd -P)" "$VS/sequences/$(basename "$seq")"
done
for method in drbokeh drbokeh_cg mpib_rt bokehme bokehme_classical ours_one_frame any_to_bokeh; do
    echo "== score $method against MPIB"
    "$PY" "$HERE/score.py" --data-root "$VS" --method "$method" --reference bokeh_mpib_rt_cg \
        ${seqs_arg[@]+"${seqs_arg[@]}"}
done
echo "== summary, against MPIB composited in gamma values"
"$PY" "$HERE/summary.py" --data-root "$VS"
