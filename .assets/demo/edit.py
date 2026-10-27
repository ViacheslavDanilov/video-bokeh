"""Turns record.cjs's screencast frames into project/assets/ui-edit.mp4.

The generation wait, from just after the click on Generate until every pane of the new
sequence shows a frame, is sped up by a whole factor, so that the film's label for it is
exact. The factor makes the wait last about GEN_EDIT seconds; the rest plays at 1x.

Under the first chapter sheet the recording waits for the API to encode the streams still to
be added, which can outlast the sheet. The part of the wait the sheet would not cover is cut
while the sheet covers the frame: from CUT_FROM after the sheet comes in to CUT_TO before the
wait ends, so the cursor moves again as the sheet leaves.

A frame in which some pane had no frame to show yet, as while a new pane's video loads,
carries record.cjs's red square in its top left corner. Those frames are left out, and the
frame before them stays up instead. Usage:
    python3 edit.py FRAMES_DIR   # then, from this folder, the ffmpeg command it prints

It prints each step mark and each press of the mouse in the edit's time and in the
film's: the demo scene starts at DEMO_START in the film, and the composition's times, the
camera's, the chapter sheets' and the click sounds', come from these.
"""

import json
import subprocess
import sys
from pathlib import Path

GEN_EDIT = 3.6  # about how many seconds the generation wait takes in the edit
DEMO_START = 4.8  # where the demo scene starts in the film, as in project/index.html
CUT_FROM, CUT_TO = 0.9, 1.1  # the cut under the first chapter sheet, in seconds

frames_dir = Path(sys.argv[1])
d = json.loads((frames_dir / "frames.json").read_text())
frames, marks = d["frames"], d["marks"]
t0 = marks["start"]
a_end = marks["generate"] - t0 + 0.42  # just after the click
b_end = marks["panes"] - t0  # every pane decoded
speed = max(1, round((b_end - a_end) / GEN_EDIT))
gen_edit = (b_end - a_end) / speed
c_start = marks["chapter2"] - t0 + CUT_FROM
c_end = max(c_start, marks["warmed"] - t0 - CUT_TO)


def edit_time(t: float) -> float:
    if t < a_end:
        return t
    if t < b_end:
        return a_end + (t - a_end) / speed
    cut = min(t, c_end) - c_start if t > c_start else 0
    return a_end + gen_edit + (t - b_end) - cut


ts = [f["t"] - t0 for f in frames]
total = edit_time(marks["end"] - t0)
# The square is 16 x 16 px at 2x; the middle 8 x 8 of it, clear of JPEG's blur at its edges.
corners = subprocess.run(
    ["ffmpeg", "-v", "error", "-start_number", "0", "-i", str(frames_dir / "%05d.jpg")]
    + ["-vf", "crop=8:8:4:4", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
    capture_output=True,
    check=True,
).stdout
red = []
for i in range(len(frames)):
    px = corners[i * 192 : (i + 1) * 192]
    r, g, b = (sum(px[c::3]) / 64 for c in range(3))
    red.append(r > 200 and g < 90 and b < 90)
kept = [
    i for i in range(len(frames)) if i == 0 or not (red[i] or c_start <= ts[i] < c_end)
]
lines = ["ffconcat version 1.0"]
for j, i in enumerate(kept):
    start = 0 if j == 0 else edit_time(ts[i])
    nxt = edit_time(ts[kept[j + 1]]) if j + 1 < len(kept) else total
    lines += [f"file '{frames[i]['name']}'", f"duration {nxt - start:.6f}"]
lines.append(f"file '{frames[kept[-1]]['name']}'")
(frames_dir / "list.ffconcat").write_text("\n".join(lines) + "\n")
print(
    f"generation wait: {b_end - a_end:.1f} s at {speed}x, {gen_edit:.2f} s in the edit"
)
print(f"sped up from {a_end:.2f} s to {a_end + gen_edit:.2f} s in the edit")
left_out = ", ".join(f"{edit_time(ts[i]):.2f}" for i in range(len(frames)) if red[i])
print(f"{sum(red)} frames left out, with an empty pane, at {left_out} s")
# The cursor must not move while frames are left out, or it would seem to jump.
spans, i = [], 0
while i < len(frames):
    if red[i]:
        j = i
        while j < len(frames) and red[j]:
            j += 1
        spans.append((ts[i], ts[j] if j < len(frames) else total))
        i = j
    i += 1
jumps = [
    (m0 - t0, m1 - t0)
    for m0, m1 in d.get("moves", [])
    if any(m0 - t0 < e and m1 - t0 > s for s, e in spans)
]
print(f"cursor moves inside a span left out: {len(jumps)}")
print(
    f"cut under the first chapter sheet: {c_end - c_start:.2f} s at {edit_time(c_start):.2f} s"
)
print(f"{'mark':10} {'edit':>7} {'film':>7}")
for name in marks:
    at = edit_time(marks[name] - t0)
    print(f"{name:10} {at:7.2f} {DEMO_START + at:7.2f}")
presses = [edit_time(t - t0) for t in d["presses"] if t >= t0]
print("presses, film:", " ".join(f"{DEMO_START + at:.2f}" for at in presses))
print(
    f"ffmpeg -y -f concat -safe 0 -i {frames_dir / 'list.ffconcat'}"
    f" -vf 'fps=30,format=yuv420p' -frames:v {int(total * 30)}"
    " -c:v libx264 -preset slow -crf 14 -movflags +faststart project/assets/ui-edit.mp4"
)
